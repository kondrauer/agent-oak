"""Functions to change the game settings on the OPTION screen."""

from pyboy import PyBoy

from agent_oak.executor.dialogue import (
    MENU_MOVE_FRAMES,
    MENU_SETTLE_FRAMES,
    PRESS_FRAMES,
    current_menu,
    select_option,
)
from agent_oak.memory.models import (
    BattleAnimation,
    BattleStyle,
    Button,
    GameOptions,
    TextSpeed,
)
from agent_oak.memory.read import (
    OPTIONS_ROWS,
    read_in_battle,
    read_is_dialogue_open,
    read_options,
    read_text_state,
)

# presses to cross the screen: the rows, or the values of the widest row
MAX_MOVES = 4
CLOSE_TRIES = 6


def _press(
    pyboy: PyBoy,
    button: Button,
    frames: int = MENU_MOVE_FRAMES,
) -> None:
    pyboy.button(button.value, delay=PRESS_FRAMES)
    pyboy.tick(frames)


def _options_open(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    menu = read_text_state(pyboy=pyboy, syms=syms).menu
    return menu is not None and menu.kind == "options"


def _open_options(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Open the OPTION screen, return whether the start menu was opened for it.

    Works from the title menu, the start menu and the overworld.
    """
    if read_in_battle(pyboy=pyboy, syms=syms):
        raise ValueError("The options can't be changed in battle")
    menu = read_text_state(pyboy=pyboy, syms=syms).menu
    opened_start = False
    if menu is None or "OPTION" not in menu.options:
        if read_is_dialogue_open(pyboy=pyboy, syms=syms):
            raise ValueError(f"Close the open dialogue or menu first: {menu}")
        _press(pyboy=pyboy, button=Button.START, frames=MENU_SETTLE_FRAMES)
        opened_start = True
        menu, _ = current_menu(pyboy=pyboy, syms=syms)
        if menu is None or "OPTION" not in menu.options:
            raise RuntimeError(f"Start menu did not open, the game shows: {menu}")

    select_option(
        pyboy=pyboy,
        syms=syms,
        index=menu.options.index("OPTION"),
    )
    if not _options_open(pyboy=pyboy, syms=syms):
        raise RuntimeError("The OPTION screen did not open")
    return opened_start


def _set_row(
    pyboy: PyBoy,
    syms: dict[str, int],
    row_y: int,
    cursor: str,
    x: int,
) -> None:
    """Move to the row at 'row_y', then its cursor to 'x'."""
    for _ in range(MAX_MOVES):
        current = pyboy.memory[syms["wTopMenuItemY"]]
        if current == row_y:
            break
        _press(pyboy=pyboy, button=Button.DOWN if current < row_y else Button.UP)
    else:
        raise RuntimeError(f"Could not move to the option row at y={row_y}")

    for _ in range(MAX_MOVES):
        current = pyboy.memory[syms[cursor]]
        if current == x:
            return
        _press(pyboy=pyboy, button=Button.RIGHT if current < x else Button.LEFT)
    raise RuntimeError(f"Could not move the {cursor} cursor to x={x}")


def set_options(
    pyboy: PyBoy,
    syms: dict[str, int],
    text_speed: TextSpeed | None = None,
    battle_animation: BattleAnimation | None = None,
    battle_style: BattleStyle | None = None,
) -> GameOptions:
    """Change the settings on the OPTION screen, then close it again.

    Opens the screen from the title menu, the start menu or the overworld
    if it is not open yet. Settings left at None keep their value.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        text_speed: FAST, MEDIUM or SLOW.
        battle_animation: ON or OFF.
        battle_style: SHIFT or SET.
    Returns:
        The settings after the change.
    """
    opened_start = False
    if not _options_open(pyboy=pyboy, syms=syms):
        opened_start = _open_options(pyboy=pyboy, syms=syms)
    pyboy.tick(MENU_SETTLE_FRAMES)

    wanted = (text_speed, battle_animation, battle_style)
    for value, (row_y, _, cursor, values) in zip(wanted, OPTIONS_ROWS):
        if value is None:
            continue
        x = next(x for x, v in values.items() if v == value)
        _set_row(pyboy=pyboy, syms=syms, row_y=row_y, cursor=cursor, x=x)

    # B leaves from any row, the settings are stored while moving
    _press(pyboy=pyboy, button=Button.B, frames=MENU_SETTLE_FRAMES)
    if opened_start:
        for _ in range(CLOSE_TRIES):
            if not read_is_dialogue_open(pyboy=pyboy, syms=syms):
                break
            _press(pyboy=pyboy, button=Button.B, frames=MENU_SETTLE_FRAMES)
    return read_options(pyboy=pyboy, syms=syms)
