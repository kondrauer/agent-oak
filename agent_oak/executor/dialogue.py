"""Functions for driving dialogues."""

import re

from pyboy import PyBoy

from agent_oak.executor.graph import shortest_path
from agent_oak.executor.models import DELTA, Node, TalkResult, World
from agent_oak.executor.navigation import BUTTON_FOR, _get_current_node, goto
from agent_oak.memory.models import Button, DialogueResult, Menu
from agent_oak.memory.read import (
    DEX_HEADER_LINES,
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


def join_texts(texts: list[str]) -> str:
    """Join the texts of consecutive dialogue calls.

    A page still on screen when the next call starts is read by both, so
    overlapping lines are only kept once.
    """
    lines: list[str] = []
    for text in texts:
        if text:
            _append_page(
                lines,
                text.split("\n"),
            )
    return "\n".join(lines)


def _press(
    pyboy: PyBoy,
    button: Button,
    frames: int,
) -> None:
    pyboy.button(button.value, delay=PRESS_FRAMES)
    pyboy.tick(frames)


def normalize_name(name: str) -> str:
    """Normalize a move, item or Pokemon name for comparison.

    "POKé BALL", "Poke Ball" and "POKE_BALL" all become "POKEBALL".
    """
    return re.sub(r"[^A-Z0-9]", "", name.upper().replace("É", "E"))


def current_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> tuple[Menu | None, list[str]]:
    """Get the menu waiting for a choice, finishing pending text first.

    Returns:
        The menu (None when the dialogue ended without one) and the text
            read on the way there.
    """
    menu = read_text_state(
        pyboy=pyboy,
        syms=syms,
    ).menu
    if menu is not None:
        return menu, []

    result = advance_dialogue(
        pyboy=pyboy,
        syms=syms,
    )
    return result.menu, [result.text] if result.text else []


def advance_dialogue(
    pyboy: PyBoy,
    syms: dict[str, int],
    timeout_frames: int = 1800,
) -> DialogueResult:
    """Read and click through text until it ends or a choice is needed.

    A is only pressed on a finished page (continue arrow shown, or the text
    has not changed for a while), never while a menu or quantity prompt is
    open. In battle it stops at the FIGHT / PKMN / ITEM / RUN menu.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        timeout_frames: The maximum number of frames to run.
    Returns:
        Every line shown, and the menu if one is waiting for a choice.
    """
    lines: list[str] = []
    last_text: list[str] | None = None
    dex_header: list[str] | None = None
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
                status="battle_menu" if state.menu.kind == "battle_menu" else "menu",
                text="\n".join(lines),
                menu=state.menu,
            )
        if state.quantity is not None:
            _append_page(
                lines,
                state.text,
            )
            return DialogueResult(
                status="quantity",
                text="\n".join(lines),
                quantity=state.quantity,
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
            page = state.text
            # later pages of a Pokedex entry repeat its name and category
            if state.dex_entry:
                header = page[:DEX_HEADER_LINES]
                if header == dex_header:
                    page = page[DEX_HEADER_LINES:]
                dex_header = header
            _append_page(
                lines,
                page,
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


def choose_quantity(
    pyboy: PyBoy,
    syms: dict[str, int],
    quantity: int,
    timeout_frames: int = 1800,
) -> DialogueResult:
    """Set the ×NN quantity prompt, confirm it and advance the dialogue.

    UP and DOWN change the quantity by one and wrap around between 1 and the
    maximum, so this goes whichever way is shorter.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        quantity: How many items, 1 up to the prompt's max.
        timeout_frames: Frame budget for the dialogue after the choice.
    Returns:
        What followed the choice, see advance_dialogue.
    """
    prompt = read_text_state(
        pyboy=pyboy,
        syms=syms,
    ).quantity
    if prompt is None:
        raise ValueError("No quantity prompt is open")
    if not 1 <= quantity <= prompt.max:
        raise ValueError(f"Quantity {quantity} out of range 1..{prompt.max}")

    pyboy.tick(MENU_SETTLE_FRAMES)
    for _ in range(prompt.max):
        current = read_text_state(
            pyboy=pyboy,
            syms=syms,
        ).quantity
        if current is None:
            raise RuntimeError("The quantity prompt closed")
        if current.value == quantity:
            break
        up = (quantity - current.value) % prompt.max
        _press(
            pyboy=pyboy,
            button=Button.UP if up <= prompt.max - up else Button.DOWN,
            frames=MENU_MOVE_FRAMES,
        )
    else:
        raise RuntimeError(f"Could not set the quantity to {quantity}")

    for _ in range(MENU_PRESS_TRIES):
        _press(
            pyboy=pyboy,
            button=Button.A,
            frames=MENU_SETTLE_FRAMES,
        )
        if read_text_state(pyboy=pyboy, syms=syms).quantity is None:
            break
    else:
        raise RuntimeError("Quantity was not accepted")
    return advance_dialogue(pyboy=pyboy, syms=syms, timeout_frames=timeout_frames)


def _move_cursor(
    pyboy: PyBoy,
    syms: dict[str, int],
    menu: Menu,
    index: int,
) -> None:
    """Move the cursor to 'index', checking the screen after every press.

    The battle menu is a 2x2 grid (FIGHT PKMN / ITEM RUN), every other menu
    is a vertical list.
    """
    for _ in range(MENU_PRESS_TRIES * len(menu.options)):
        current = read_text_state(
            pyboy=pyboy,
            syms=syms,
        ).menu
        if current is None:
            break
        if current.selected == index:
            return

        if menu.kind == "battle_menu":
            (row, col), (target_row, target_col) = (
                divmod(current.selected, 2),
                divmod(index, 2),
            )
            if row != target_row:
                button = Button.DOWN if row < target_row else Button.UP
            else:
                button = Button.RIGHT if col < target_col else Button.LEFT
        else:
            button = Button.DOWN if current.selected < index else Button.UP

        _press(
            pyboy=pyboy,
            button=button,
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
