"""Functions to drive a battle.

Thin wrappers around select_option: they pick menu entries by name instead
of by index and return the turn together with the battle state.
"""

from pyboy import PyBoy

from agent_oak.executor.dialogue import (
    MENU_SETTLE_FRAMES,
    PRESS_FRAMES,
    advance_dialogue,
    current_menu,
    join_texts,
    normalize_name,
    select_option,
)
from agent_oak.memory.models import BattleTurn, Button, DialogueResult
from agent_oak.memory.read import read_battle_state

FIGHT, PKMN, ITEM, RUN = 0, 1, 2, 3
# the upper two bits of a PP byte count PP Ups
PP_MASK = 0x3F


def battle_turn(
    pyboy: PyBoy,
    syms: dict[str, int],
    texts: list[str],
    result: DialogueResult,
) -> BattleTurn:
    """Join the texts before 'result' with it and add the battle state."""
    return BattleTurn(
        dialogue=result.model_copy(update={"text": join_texts([*texts, result.text])}),
        battle=read_battle_state(
            pyboy=pyboy,
            syms=syms,
        ),
    )


def require_battle_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> list[str]:
    """Finish pending text, fail unless the battle menu waits for a choice."""
    menu, texts = current_menu(
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
    texts = require_battle_menu(
        pyboy=pyboy,
        syms=syms,
    )
    mon = read_battle_state(
        pyboy=pyboy,
        syms=syms,
    ).player_pokemon
    if mon is None:
        raise ValueError("No active Pokemon")

    names = [normalize_name(m) for m in mon.moves]
    if normalize_name(move) not in names:
        raise ValueError(f"{mon.species} does not know {move}, moves: {mon.moves}")
    index = names.index(normalize_name(move))
    if mon.pp[index] & PP_MASK == 0:
        raise ValueError(f"{move} has no PP left")

    move_menu = select_option(
        pyboy=pyboy,
        syms=syms,
        index=FIGHT,
    )
    if move_menu.menu is None or move_menu.menu.kind != "move_menu":
        return battle_turn(
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
    return battle_turn(
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
    menu, texts = current_menu(
        pyboy=pyboy,
        syms=syms,
    )
    voluntary = menu is not None and menu.kind == "battle_menu"
    if voluntary:
        active = read_battle_state(
            pyboy=pyboy,
            syms=syms,
        ).player_pokemon
        if active is not None and normalize_name(
            active.nickname or ""
        ) == normalize_name(pokemon):
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

    names = [normalize_name(n) for n in menu.options]
    if normalize_name(pokemon) not in names:
        raise ValueError(f"{pokemon} is not in the party: {menu.options}")

    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=names.index(normalize_name(pokemon)),
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
    return battle_turn(
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
    texts = require_battle_menu(
        pyboy=pyboy,
        syms=syms,
    )
    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=RUN,
    )
    return battle_turn(
        pyboy=pyboy,
        syms=syms,
        texts=texts,
        result=result,
    )
