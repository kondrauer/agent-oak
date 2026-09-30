"""Functions to drive a battle.

Thin wrappers around select_option: they pick menu entries by name instead
of by index and return the turn together with the battle state.
"""

import re

from pyboy import PyBoy

from agent_oak.executor.dialogue import (
    MENU_SETTLE_FRAMES,
    PRESS_FRAMES,
    advance_dialogue,
    select_option,
)
from agent_oak.memory.models import BattleTurn, Button, DialogueResult, Menu
from agent_oak.memory.read import read_battle_state, read_text_state

FIGHT, PKMN, RUN = 0, 1, 3
# the upper two bits of a PP byte count PP Ups
PP_MASK = 0x3F


def _normalize(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _current_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> tuple[Menu | None, list[str]]:
    """Get the menu waiting for a choice, finishing pending text first."""
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


def _turn(
    pyboy: PyBoy,
    syms: dict[str, int],
    texts: list[str],
    result: DialogueResult,
) -> BattleTurn:
    return BattleTurn(
        dialogue=result.model_copy(
            update={"text": "\n".join(t for t in [*texts, result.text] if t)}
        ),
        battle=read_battle_state(
            pyboy=pyboy,
            syms=syms,
        ),
    )


def _require_battle_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> list[str]:
    menu, texts = _current_menu(
        pyboy=pyboy,
        syms=syms,
    )
    if menu is None or menu.kind != "battle_menu":
        raise ValueError(f"Not at the battle menu, the game shows: {menu}")
    return texts


def battle_use_move(
    pyboy: PyBoy,
    syms: dict[str, int],
    move: str,
) -> BattleTurn:
    """Use a move of the active Pokemon.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        move: Move name, e.g. "TACKLE" (case and punctuation are ignored).
    Returns:
        The turn's text up to the next decision and the battle state.
    """
    texts = _require_battle_menu(
        pyboy=pyboy,
        syms=syms,
    )
    mon = read_battle_state(
        pyboy=pyboy,
        syms=syms,
    ).player_pokemon
    if mon is None:
        raise ValueError("No active Pokemon")

    names = [_normalize(m) for m in mon.moves]
    if _normalize(move) not in names:
        raise ValueError(f"{mon.species} does not know {move}, moves: {mon.moves}")
    index = names.index(_normalize(move))
    if mon.pp[index] & PP_MASK == 0:
        raise ValueError(f"{move} has no PP left")

    move_menu = select_option(
        pyboy=pyboy,
        syms=syms,
        index=FIGHT,
    )
    if move_menu.menu is None or move_menu.menu.kind != "move_menu":
        return _turn(
            pyboy=pyboy,
            syms=syms,
            texts=texts,
            result=move_menu,
        )

    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=index,
    )
    return _turn(
        pyboy=pyboy,
        syms=syms,
        texts=[*texts, move_menu.text],
        result=result,
    )


def battle_switch(
    pyboy: PyBoy,
    syms: dict[str, int],
    pokemon: str,
) -> BattleTurn:
    """Switch to another party Pokemon.

    Also works for the forced switch after the active Pokemon fainted, when
    the game opens the party menu by itself.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        pokemon: Nickname of the party Pokemon to send out.
    Returns:
        The turn's text up to the next decision and the battle state.
    """
    menu, texts = _current_menu(
        pyboy=pyboy,
        syms=syms,
    )
    voluntary = menu is not None and menu.kind == "battle_menu"
    if voluntary:
        active = read_battle_state(
            pyboy=pyboy,
            syms=syms,
        ).player_pokemon
        if active is not None and _normalize(active.nickname or "") == _normalize(
            pokemon
        ):
            raise ValueError(f"{pokemon} is already out")
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=PKMN,
        )
        texts.append(result.text)
        menu = result.menu
    if menu is None or menu.kind != "party_menu":
        raise ValueError(f"Party menu did not open, the game shows: {menu}")

    names = [_normalize(n) for n in menu.options]
    if _normalize(pokemon) not in names:
        raise ValueError(f"{pokemon} is not in the party: {menu.options}")

    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=names.index(_normalize(pokemon)),
    )
    # a voluntary switch asks SWITCH / STATS / CANCEL first
    if result.menu is not None and "SWITCH" in result.menu.options:
        texts.append(result.text)
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=result.menu.options.index("SWITCH"),
        )
    # refused (fainted, ...), back out so the battle menu is usable again
    if voluntary and result.menu is not None and result.menu.kind == "party_menu":
        texts.append(result.text)
        pyboy.button(Button.B.value, delay=PRESS_FRAMES)
        pyboy.tick(MENU_SETTLE_FRAMES)
        result = advance_dialogue(
            pyboy=pyboy,
            syms=syms,
        )
    return _turn(
        pyboy=pyboy,
        syms=syms,
        texts=texts,
        result=result,
    )


def battle_run(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> BattleTurn:
    """Try to run from a wild battle.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
    Returns:
        The text (escaped, or failed and the enemy's turn) and the battle
            state.
    """
    texts = _require_battle_menu(
        pyboy=pyboy,
        syms=syms,
    )
    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=RUN,
    )
    return _turn(
        pyboy=pyboy,
        syms=syms,
        texts=texts,
        result=result,
    )
