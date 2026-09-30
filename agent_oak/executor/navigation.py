"""Functions for exectuing navigation."""

from pyboy import PyBoy

from agent_oak.executor.graph import shortest_path
from agent_oak.executor.models import Edge, GotoStatus, Node, World
from agent_oak.memory.models import Button
from agent_oak.memory.read import (
    read_in_battle,
    read_is_dialogue_open,
    read_location,
    read_npcs,
)
from agent_oak.parser.models import Direction, GameMap

DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WALK_HOLD_FRAMES = 12
WALK_SETTLE_FRAMES = 8
WALK_TIMEOUT_FRAMES = 40
MAP_TRANSITION_SETTLE_FRAMES = 60
MAP_TRANSITION_TIMEOUT_FRAMES = 120

BUTTON_FOR = {
    Direction.NORTH: Button.UP,
    Direction.SOUTH: Button.DOWN,
    Direction.WEST: Button.LEFT,
    Direction.EAST: Button.RIGHT,
}


def _get_current_node(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
) -> Node:
    loc = read_location(
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
    )

    return (loc.map.const, loc.x, loc.y)


def _get_settled_node(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
    world: World,
) -> Node:
    """Get the current node, waiting out a warp that is still in progress."""
    node = _get_current_node(pyboy=pyboy, syms=syms, maps_by_id=maps_by_id)
    if not world.maybe_mid_warp(node=node):
        return node

    # a real position can look like a mid warp one too, then this just waits
    # out the timeout and returns it unchanged
    for _ in range(MAP_TRANSITION_TIMEOUT_FRAMES):
        pyboy.tick()
        if _get_current_node(pyboy=pyboy, syms=syms, maps_by_id=maps_by_id) != node:
            # destination x, y are written, let the fade in finish
            pyboy.tick(MAP_TRANSITION_SETTLE_FRAMES)
            break
    return _get_current_node(pyboy=pyboy, syms=syms, maps_by_id=maps_by_id)


def _interruption(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> GotoStatus | None:
    """Why walking cannot continue right now, if anything is in the way."""
    if read_in_battle(pyboy=pyboy, syms=syms):
        return "in_battle"
    if read_is_dialogue_open(pyboy=pyboy, syms=syms):
        return "dialogue_open"
    return None


def _tick_until(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
    target: Node,
    frames: int,
) -> bool:
    """Tick until the player stands on 'target', at most 'frames' frames."""
    for _ in range(frames):
        if _get_current_node(pyboy=pyboy, syms=syms, maps_by_id=maps_by_id) == target:
            return True
        pyboy.tick()
    return _get_current_node(pyboy=pyboy, syms=syms, maps_by_id=maps_by_id) == target


def _wait_walk_done(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> None:
    """Tick until the step animation is over, then let the game settle."""
    for _ in range(WALK_TIMEOUT_FRAMES):
        if pyboy.memory[syms["wWalkCounter"]] == 0:
            break
        pyboy.tick()
    pyboy.tick(WALK_SETTLE_FRAMES)


def _press_button_with_delay(
    pyboy: PyBoy,
    button: Button,
) -> None:
    pyboy.button(
        button.value,
        delay=WALK_HOLD_FRAMES,
    )


def _edge_button(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
) -> Button | None:
    """Get the button that walks off the map edge the player stands on."""
    loc = read_location(
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
    )
    if loc.y == loc.map.step_height - 1:
        return Button.DOWN
    if loc.y == 0:
        return Button.UP
    if loc.x == 0:
        return Button.LEFT
    if loc.x == loc.map.step_width - 1:
        return Button.RIGHT
    return None


def _execute_step(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
    step: Edge,
    last_button: Button | None,
) -> bool:
    """Execute a single edge, return whether the player ended up on its dst."""
    if step.kind == "warp":
        # door tiles warp as soon as you step on them, so we may already be
        # mid transition or through it
        if not _tick_until(
            pyboy=pyboy,
            syms=syms,
            maps_by_id=maps_by_id,
            target=step.dst,
            frames=MAP_TRANSITION_TIMEOUT_FRAMES,
        ):
            # edge of map warps (house mats) need a push off the map edge,
            # which is not the direction we came from when entering the mat
            # from the side
            button = (
                _edge_button(
                    pyboy=pyboy,
                    syms=syms,
                    maps_by_id=maps_by_id,
                )
                or last_button
            )
            if button is None:
                return False
            _press_button_with_delay(pyboy=pyboy, button=button)
            if not _tick_until(
                pyboy=pyboy,
                syms=syms,
                maps_by_id=maps_by_id,
                target=step.dst,
                frames=MAP_TRANSITION_TIMEOUT_FRAMES,
            ):
                return False
        pyboy.tick(MAP_TRANSITION_SETTLE_FRAMES)
        return True

    if step.direction is None:
        return False

    _press_button_with_delay(pyboy=pyboy, button=BUTTON_FOR[step.direction])
    arrived = _tick_until(
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
        target=step.dst,
        # a ledge hop covers two tiles
        frames=WALK_TIMEOUT_FRAMES * (2 if step.kind == "ledge" else 1),
    )
    _wait_walk_done(pyboy=pyboy, syms=syms)
    if step.kind == "connection":
        pyboy.tick(MAP_TRANSITION_SETTLE_FRAMES)
    return arrived


def goto(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
    world: World,
    goal: Node,
    max_replans: int = 10,
) -> GotoStatus:
    """Go to a waypoint.

    Plans a path from the current position, walks it and replans from
    wherever the player is whenever a step does not land where expected
    (NPC in the way, ...). Stops early when a battle or a text box
    interrupts the walk, the caller has to deal with it and call again.

    Returns:
        "reached" when the player ended up on 'goal', otherwise why not.
    """
    for _ in range(max_replans + 1):
        node = _get_settled_node(
            pyboy=pyboy,
            syms=syms,
            maps_by_id=maps_by_id,
            world=world,
        )
        if node == goal:
            return "reached"
        if (reason := _interruption(pyboy=pyboy, syms=syms)) is not None:
            return reason

        npcs = {(node[0], n.x, n.y) for n in read_npcs(pyboy=pyboy, syms=syms)}
        path = shortest_path(
            world=world,
            start=node,
            goal=goal,
            blocked=lambda n: n in npcs,
        )
        if path is None:
            return "no_path"

        last_button: Button | None = None
        for step in path:
            if not _execute_step(
                pyboy=pyboy,
                syms=syms,
                maps_by_id=maps_by_id,
                step=step,
                last_button=last_button,
            ):
                break
            if step.direction is not None:
                last_button = BUTTON_FOR[step.direction]

    node = _get_settled_node(
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
        world=world,
    )
    if node == goal:
        return "reached"
    return _interruption(pyboy=pyboy, syms=syms) or "gave_up"
