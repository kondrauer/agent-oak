"""Functions for driving dialogues."""

from pyboy import PyBoy

from agent_oak.executor.graph import shortest_path
from agent_oak.executor.models import DELTA, Node, TalkResult, World
from agent_oak.executor.navigation import BUTTON_FOR, _get_current_node, goto
from agent_oak.memory.models import Button, DialogueResult, Menu
from agent_oak.memory.read import (
    read_in_battle,
    read_is_dialogue_open,
    read_npcs,
    read_player_facing,
    read_text_state,
)
from agent_oak.parser.models import Direction, GameMap

PRESS_FRAMES = 4
AFTER_PRESS_FRAMES = 8
MENU_MOVE_FRAMES = 12
# a fresh menu ignores input for a few frames before it polls the joypad
MENU_SETTLE_FRAMES = 20
MENU_PRESS_TRIES = 3
# the last page has no continue arrow, it just sits there until A is pressed
PAGE_STABLE_FRAMES = 40
# text boxes can take a moment to show up after talking to someone
BOX_CLOSED_FRAMES = 60
FACE_TIMEOUT_FRAMES = 20


def _append_page(
    lines: list[str],
    page: list[str],
) -> None:
    """Append a page, skipping lines still on screen from the previous one.

    Pages scroll one line at a time, and a page can be read again when a
    menu opens on top of it, so drop the longest overlap with what we have.
    """
    for k in range(min(len(lines), len(page)), 0, -1):
        if lines[-k:] == page[:k]:
            lines.extend(page[k:])
            return
    lines.extend(page)


def _press(
    pyboy: PyBoy,
    button: Button,
    frames: int,
) -> None:
    pyboy.button(button.value, delay=PRESS_FRAMES)
    pyboy.tick(frames)


def advance_dialogue(
    pyboy: PyBoy,
    syms: dict[str, int],
    timeout_frames: int = 1800,
) -> DialogueResult:
    """Read and click through text until it ends or a choice is needed.

    A is only pressed on a finished page (continue arrow shown, or the text
    has not changed for a while), never while a menu is open. In battle it
    stops at the FIGHT / PKMN / ITEM / RUN menu.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        timeout_frames: The maximum number of frames to run.
    Returns:
        Every line shown, and the menu if one is waiting for a choice.
    """
    lines: list[str] = []
    last_text: list[str] | None = None
    stable = closed = 0
    frame = 0

    while frame < timeout_frames:
        state = read_text_state(pyboy=pyboy, syms=syms)

        if state.menu is not None:
            # the battle menu is drawn over the text box
            if state.menu.kind != "battle_menu":
                _append_page(
                    lines,
                    state.text,
                )
            return DialogueResult(
                status=state.menu.kind,
                text="\n".join(lines),
                menu=state.menu,
            )

        # scripted scenes (NPC walking the player somewhere) lock the joypad
        # between their text boxes and battle intros keep the window up,
        # wait for both to end
        idle = (
            not state.box_open
            and pyboy.memory[syms["wJoyIgnore"]] == 0
            and not read_is_dialogue_open(pyboy=pyboy, syms=syms)
        )
        closed = closed + 1 if idle else 0
        # battles keep their box open, between boxes the screen is animating
        if closed >= BOX_CLOSED_FRAMES and not read_in_battle(pyboy=pyboy, syms=syms):
            return DialogueResult(status="done", text="\n".join(lines))

        stable = stable + 1 if state.text == last_text else 0
        last_text = state.text

        if state.text and (state.waiting_for_a or stable >= PAGE_STABLE_FRAMES):
            _append_page(
                lines,
                state.text,
            )
            _press(
                pyboy=pyboy,
                button=Button.A,
                frames=AFTER_PRESS_FRAMES,
            )
            frame += AFTER_PRESS_FRAMES
            stable, last_text = 0, None
            continue

        pyboy.tick()
        frame += 1

    return DialogueResult(
        status="timeout",
        text="\n".join(lines),
    )


def select_option(
    pyboy: PyBoy,
    syms: dict[str, int],
    index: int,
    timeout_frames: int = 1800,
) -> DialogueResult:
    """Pick an option of the open menu, then advance the dialogue after it.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        index: Index into the menu's options.
        timeout_frames: Frame budget for the dialogue after the choice.
    Returns:
        What followed the choice, see advance_dialogue.
    """
    menu = read_text_state(
        pyboy=pyboy,
        syms=syms,
    ).menu
    if menu is None:
        raise ValueError("No menu is open")
    if menu.kind == "battle_menu":
        raise ValueError("The battle menu is not handled by select_option yet")
    if not 0 <= index < len(menu.options):
        raise ValueError(f"Index {index} out of range for options {menu.options}")

    pyboy.tick(MENU_SETTLE_FRAMES)
    _move_cursor(
        pyboy=pyboy,
        syms=syms,
        menu=menu,
        index=index,
    )
    for _ in range(MENU_PRESS_TRIES):
        _press(
            pyboy=pyboy,
            button=Button.A,
            frames=MENU_SETTLE_FRAMES,
        )
        if read_text_state(
            pyboy=pyboy,
            syms=syms,
        ).menu != menu.model_copy(update={"selected": index}):
            break
    else:
        raise RuntimeError(f"Option {index} was not accepted")
    return advance_dialogue(pyboy=pyboy, syms=syms, timeout_frames=timeout_frames)


def _move_cursor(
    pyboy: PyBoy,
    syms: dict[str, int],
    menu: Menu,
    index: int,
) -> None:
    for _ in range(MENU_PRESS_TRIES * len(menu.options)):
        current = pyboy.memory[syms["wCurrentMenuItem"]]
        if current == index:
            return
        _press(
            pyboy=pyboy,
            button=Button.DOWN if current < index else Button.UP,
            frames=MENU_MOVE_FRAMES,
        )
    raise RuntimeError(f"Could not move the cursor to option {index}")


def _stand_tiles(
    world: World,
    target: Node,
    occupied: set[Node],
) -> list[tuple[Node, Direction]]:
    """Tiles to talk to 'target' from, with the direction to face.

    Next to it, or two tiles away across a counter (Pokecenter, Mart, ...).
    """
    const, x, y = target
    counters = world.tilesets[world.maps[const].tileset].counter_tiles
    out = []
    for d, (dx, dy) in DELTA.items():
        near: Node = (const, x - dx, y - dy)
        if world.terrain(node=near) == "land" and near not in occupied:
            out.append((near, d))
        elif world.in_bounds(near) and world.collision_tile(near) in counters:
            far: Node = (const, x - 2 * dx, y - 2 * dy)
            if world.terrain(node=far) == "land" and far not in occupied:
                out.append((far, d))
    return out


def _npc_at(
    pyboy: PyBoy,
    syms: dict[str, int],
    x: int,
    y: int,
) -> int | None:
    return next(
        (n.slot for n in read_npcs(pyboy=pyboy, syms=syms) if (n.x, n.y) == (x, y)),
        None,
    )


def _face(
    pyboy: PyBoy,
    syms: dict[str, int],
    direction: Direction,
) -> None:
    if (
        read_player_facing(
            pyboy=pyboy,
            syms=syms,
        )
        is direction
    ):
        return
    # the target blocks the tile ahead, so this only turns the player
    pyboy.button(
        BUTTON_FOR[direction].value,
        delay=PRESS_FRAMES,
    )
    for _ in range(FACE_TIMEOUT_FRAMES):
        pyboy.tick()
        if (
            read_player_facing(
                pyboy=pyboy,
                syms=syms,
            )
            is direction
        ):
            break
    pyboy.tick(AFTER_PRESS_FRAMES)


def talk_to(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
    world: World,
    x: int,
    y: int,
    max_attempts: int = 2,
) -> TalkResult:
    """Walk next to an NPC, sign or object on the current map and talk to it.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        maps_by_id: Parsed game maps keyed by map id.
        world: The world model used for pathfinding.
        x: Target x in steps on the current map.
        y: Target y in steps on the current map.
        max_attempts: How often to follow an NPC that walked away.
    Returns:
        How walking there went and the dialogue, if it was started.
    """
    const = _get_current_node(
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
    )[0]
    slot = _npc_at(
        pyboy=pyboy,
        syms=syms,
        x=x,
        y=y,
    )

    for _ in range(max_attempts):
        if slot is not None:
            npc = next(
                (n for n in read_npcs(pyboy=pyboy, syms=syms) if n.slot == slot),
                None,
            )
            if npc is None:
                return TalkResult(walk="no_path")
            x, y = npc.x, npc.y

        start = _get_current_node(
            pyboy=pyboy,
            syms=syms,
            maps_by_id=maps_by_id,
        )
        occupied = {(const, n.x, n.y) for n in read_npcs(pyboy=pyboy, syms=syms)}
        best: tuple[int, Node, Direction] | None = None
        for stand, direction in _stand_tiles(
            world=world,
            target=(const, x, y),
            occupied=occupied,
        ):
            path = (
                []
                if stand == start
                else shortest_path(
                    world=world,
                    start=start,
                    goal=stand,
                    blocked=lambda n: n in occupied,
                )
            )
            if path is not None and (best is None or len(path) < best[0]):
                best = (len(path), stand, direction)
        if best is None:
            return TalkResult(walk="no_path")

        _, stand, direction = best
        status = goto(
            pyboy=pyboy,
            syms=syms,
            maps_by_id=maps_by_id,
            world=world,
            goal=stand,
        )
        if status != "reached":
            return TalkResult(walk=status)
        if slot is not None and _npc_at(pyboy=pyboy, syms=syms, x=x, y=y) != slot:
            continue

        _face(pyboy=pyboy, syms=syms, direction=direction)
        _press(pyboy=pyboy, button=Button.A, frames=AFTER_PRESS_FRAMES)
        return TalkResult(
            walk="reached",
            dialogue=advance_dialogue(pyboy=pyboy, syms=syms),
        )

    return TalkResult(walk="gave_up")
