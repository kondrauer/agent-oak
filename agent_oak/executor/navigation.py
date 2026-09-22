"""Functions for exectuing navigation."""

from networkx import MultiDiGraph
from pyboy import PyBoy

from agent_oak.memory.read import (
    read_in_battle,
    read_is_dialogue_open,
    read_location,
)
from agent_oak.parser.models import GameMap

DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WALK_HOLD_FRAMES = 12
WALK_SETTLE_FRAMES = 8
MAP_TRANSITION_SETTLE_FRAMES = 60


def build_game_map_graph(game_maps: dict[str, GameMap]) -> MultiDiGraph:
    """Build a graph out of the game_maps dict."""
    G = MultiDiGraph()

    for m in game_maps.values():
        G.add_node(m.const, model=m)

        for c in m.connections:
            G.add_edge(
                m.const,
                c.target_const,
                kind="connection",
                direction=c.direction,
                offset=c.offset,
            )

        for i, w in enumerate(m.warps):
            if w.dest_map != "LAST_MAP":
                G.add_edge(
                    m.const,
                    w.dest_map,
                    kind="warp",
                    src_warp=i,
                    dest_warp=w.dest_warp,
                    x=w.x,
                    y=w.y,
                )

    return G


def walk_to(
    pyboy: PyBoy,
    syms: dict[str, int],
    x: int,
    y: int,
    max_steps: int = 150,
) -> dict[str, object]:
    """Walk toward (x, y) on the current map, one tile at a time.

    There is no vendored collision/warp data for the ROM, so this moves
    greedily toward the target and detects walls by checking whether the
    player's coordinates actually changed after a button press ("bump
    detection"), backing off directions that turned out to be blocked from
    a given tile. It stops as soon as the map changes (e.g. stairs or a
    door were used), the target tile is reached, a battle or dialogue
    interrupts, or no direction makes progress.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        x: The target x coordinate on the current map.
        y: The target y coordinate on the current map.
        max_steps: The maximum number of tile-moves to attempt.
    Returns:
        A dictionary containing the status
            (arrived/map_changed/interupt/stuck/timeout) and final location.
    """
    start_map = read_location(pyboy=pyboy, syms=syms).map_id
    blocked: set[tuple[int, int, str]] = set()

    for _ in range(max_steps):
        loc = read_location(pyboy=pyboy, syms=syms)

        if loc.map_id != start_map:
            # The map/coordinate bytes update in separate writes during the
            # transition, so let it fully settle before reporting location.
            for _ in range(MAP_TRANSITION_SETTLE_FRAMES):
                pyboy.tick()
            loc = read_location(pyboy=pyboy, syms=syms)
            return {"status": "map_changed", "location": loc.model_dump()}
        if loc.x == x and loc.y == y:
            return {"status": "arrived", "location": loc.model_dump()}
        if read_in_battle(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "battle",
                "location": loc.model_dump(),
            }
        if read_is_dialogue_open(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "dialogue",
                "location": loc.model_dump(),
            }

        dx, dy = x - loc.x, y - loc.y
        toward = []
        if dx > 0:
            toward.append("right")
        elif dx < 0:
            toward.append("left")
        if dy > 0:
            toward.append("down")
        elif dy < 0:
            toward.append("up")
        if abs(dy) > abs(dx):
            toward.reverse()
        # Prefer sideways detours over backtracking away from the target,
        # e.g. don't retreat "up" just because "down" is blocked.
        avoid = {OPPOSITE[d] for d in toward}
        sideways = [d for d in DIRECTIONS if d not in toward and d not in avoid]
        backtrack = [d for d in DIRECTIONS if d not in toward and d in avoid]
        order = toward + sideways + backtrack
        unblocked = [d for d in order if (loc.x, loc.y, d) not in blocked]

        moved = False
        for direction in unblocked or order:
            pyboy.button(direction, delay=WALK_HOLD_FRAMES)
            for _ in range(WALK_HOLD_FRAMES + WALK_SETTLE_FRAMES):
                pyboy.tick()
            new_loc = read_location(pyboy=pyboy, syms=syms)
            if (new_loc.map_id, new_loc.x, new_loc.y) != (loc.map_id, loc.x, loc.y):
                moved = True
                break
            blocked.add((loc.x, loc.y, direction))

        if not moved:
            return {"status": "stuck", "location": loc.model_dump()}

    return {
        "status": "timeout",
        "location": read_location(pyboy=pyboy, syms=syms).model_dump(),
    }


def goto(waypoint: str):
    """Go to a waypoint."""
    pass
