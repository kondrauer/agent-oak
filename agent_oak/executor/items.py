"""Functions to use, buy and sell items.

Thin wrappers around select_option and choose_quantity: they walk the
start menu, the battle menu and the mart menus and pick items and Pokemon by
name instead of by index.
"""

import re
from typing import Literal

from pyboy import PyBoy

from agent_oak.executor.battle import ITEM, battle_turn, require_battle_menu
from agent_oak.executor.dialogue import (
    MENU_SETTLE_FRAMES,
    PRESS_FRAMES,
    choose_quantity,
    current_menu,
    join_texts,
    normalize_name,
    select_option,
)
from agent_oak.memory.models import BattleTurn, Button, DialogueResult, Menu
from agent_oak.memory.read import (
    read_battle_state,
    read_in_battle,
    read_is_dialogue_open,
    read_text_state,
)

# price or quantity after an item name in a list menu, e.g. " ¥200", " ×3"
LIST_SUFFIX = re.compile(r" [¥×]\d+$")
YES = 0
CLOSE_TRIES = 6


def _option_index(
    menu: Menu,
    name: str,
) -> int | None:
    """Index of the option called 'name', ignoring list prices / quantities."""
    names = [normalize_name(LIST_SUFFIX.sub("", o)) for o in menu.options]
    return names.index(normalize_name(name)) if normalize_name(name) in names else None


def _press_b(pyboy: PyBoy) -> None:
    pyboy.button(Button.B.value, delay=PRESS_FRAMES)
    pyboy.tick(MENU_SETTLE_FRAMES)


def _close_menus(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> None:
    """Back out of the bag and start menu to the overworld."""
    for _ in range(CLOSE_TRIES):
        if read_text_state(
            pyboy=pyboy,
            syms=syms,
        ).menu is None and not read_is_dialogue_open(
            pyboy=pyboy,
            syms=syms,
        ):
            return
        _press_b(pyboy=pyboy)


def _back_to_battle_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> None:
    """Back out of the bag or party list to FIGHT / PKMN / ITEM / RUN."""
    for _ in range(CLOSE_TRIES):
        menu = read_text_state(
            pyboy=pyboy,
            syms=syms,
        ).menu
        if menu is not None and menu.kind == "battle_menu":
            return
        _press_b(pyboy=pyboy)


def _pick_target(
    pyboy: PyBoy,
    syms: dict[str, int],
    party_menu: Menu,
    target: str | None,
    texts: list[str],
) -> DialogueResult:
    """Answer "Use item on which POKéMON?" with 'target'.

    Without a target this defaults to the active Pokemon in battle and to
    the only Pokemon outside of it.
    """
    if target is None:
        active = read_battle_state(
            pyboy=pyboy,
            syms=syms,
        ).player_pokemon
        if active is not None and active.nickname:
            target = active.nickname
        elif len(party_menu.options) == 1:
            target = party_menu.options[0]
        else:
            raise ValueError(f"Pass a target, one of {party_menu.options}")

    index = _option_index(party_menu, target)
    if index is None:
        raise ValueError(f"{target} is not in the party: {party_menu.options}")
    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=index,
    )
    texts.append(result.text)
    return result


def use_item(
    pyboy: PyBoy,
    syms: dict[str, int],
    item: str,
    target: str | None = None,
) -> BattleTurn | DialogueResult:
    """Use an item from the bag, in battle or on the overworld.

    In battle this goes through ITEM on the battle menu and returns the
    turn. Outside of battle it opens the start menu, uses the item and
    closes the menus again.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        item: Item name, e.g. "POTION" or "POKé BALL" (case, accents and
            punctuation are ignored).
        target: Nickname of the party Pokemon for items like POTION.
            Defaults to the active Pokemon in battle, and to the only party
            Pokemon outside of it.
    Returns:
        The turn and battle state in battle, the dialogue outside of it.
            Prompts the game asks afterwards (e.g. teaching a TM) come back
            as a menu, answer them with select_option.
    """
    in_battle = read_in_battle(pyboy=pyboy, syms=syms)
    if in_battle:
        texts = require_battle_menu(
            pyboy=pyboy,
            syms=syms,
        )
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=ITEM,
        )
    else:
        if read_is_dialogue_open(pyboy=pyboy, syms=syms):
            raise ValueError("Close the open dialogue or menu first")
        texts = []
        pyboy.button(Button.START.value, delay=PRESS_FRAMES)
        pyboy.tick(MENU_SETTLE_FRAMES)
        start_menu, _ = current_menu(
            pyboy=pyboy,
            syms=syms,
        )
        index = None if start_menu is None else _option_index(start_menu, "ITEM")
        if index is None:
            _close_menus(pyboy=pyboy, syms=syms)
            raise RuntimeError(f"Start menu did not open, the game shows: {start_menu}")
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=index,
        )

    if result.menu is None or result.menu.kind != "list_menu":
        raise RuntimeError(f"Bag did not open, the game shows: {result}")
    index = _option_index(result.menu, item)
    if index is None or result.menu.options[index] == "CANCEL":
        options = result.menu.options[:-1]
        if in_battle:
            _back_to_battle_menu(pyboy=pyboy, syms=syms)
        else:
            _close_menus(pyboy=pyboy, syms=syms)
        raise ValueError(f"{item} is not in the bag: {options}")

    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=index,
    )
    texts.append(result.text)
    # outside of battle the bag asks USE / TOSS first
    if result.menu is not None and result.menu.options == ["USE", "TOSS"]:
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=0,
        )
        texts.append(result.text)
    if result.menu is not None and result.menu.kind == "party_menu":
        try:
            result = _pick_target(
                pyboy=pyboy,
                syms=syms,
                party_menu=result.menu,
                target=target,
                texts=texts,
            )
        except ValueError:
            if in_battle:
                _back_to_battle_menu(pyboy=pyboy, syms=syms)
            else:
                _close_menus(pyboy=pyboy, syms=syms)
            raise

    if in_battle:
        return battle_turn(
            pyboy=pyboy,
            syms=syms,
            texts=texts[:-1],
            result=result,
        )
    # the bag opens again after an item was used
    if result.menu is not None and result.menu.kind == "list_menu":
        _close_menus(pyboy=pyboy, syms=syms)
        result = result.model_copy(update={"status": "done", "menu": None})
    return result.model_copy(update={"text": join_texts(texts)})


def _trade(
    pyboy: PyBoy,
    syms: dict[str, int],
    action: Literal["BUY", "SELL"],
    item: str,
    quantity: int,
) -> DialogueResult:
    """Buy or sell at a mart, starting at BUY / SELL / QUIT or in the list."""
    menu, texts = current_menu(
        pyboy=pyboy,
        syms=syms,
    )
    # the other list is open (bag entries show ×quantity), back to the menu
    if menu is not None and menu.kind == "list_menu":
        is_bag = any("×" in o for o in menu.options)
        if is_bag != (action == "SELL"):
            result = select_option(
                pyboy=pyboy,
                syms=syms,
                index=len(menu.options) - 1,
            )
            texts.append(result.text)
            menu = result.menu
    action_index = None if menu is None else _option_index(menu, action)
    if action_index is not None:
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=action_index,
        )
        texts.append(result.text)
        menu = result.menu
    if menu is None or menu.kind != "list_menu":
        raise ValueError(
            f"Not at a mart menu, talk to the clerk first. The game shows: {menu}"
        )

    index = _option_index(menu, item)
    if index is None or menu.options[index] == "CANCEL":
        raise ValueError(f"{item} is not in the list: {menu.options[:-1]}")
    result = select_option(
        pyboy=pyboy,
        syms=syms,
        index=index,
    )
    texts.append(result.text)
    if result.quantity is not None:
        result = choose_quantity(
            pyboy=pyboy,
            syms=syms,
            quantity=min(quantity, result.quantity.max),
        )
        texts.append(result.text)
    # "That will be ¥600. OK?" / "I can pay you ¥75 for that."
    if result.menu is not None and result.menu.options == ["YES", "NO"]:
        result = select_option(
            pyboy=pyboy,
            syms=syms,
            index=YES,
        )
        texts.append(result.text)
    return result.model_copy(update={"text": join_texts(texts)})


def buy_item(
    pyboy: PyBoy,
    syms: dict[str, int],
    item: str,
    quantity: int = 1,
) -> DialogueResult:
    """Buy an item from the mart clerk.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        item: Item name, e.g. "POKé BALL" (case and accents are ignored).
        quantity: How many to buy.
    Returns:
        The clerk's answer and the menu after it: the buy list again, or
            BUY / SELL / QUIT when the money was not enough.
    """
    if quantity < 1:
        raise ValueError("Quantity must be at least 1")
    return _trade(
        pyboy=pyboy,
        syms=syms,
        action="BUY",
        item=item,
        quantity=quantity,
    )


def sell_item(
    pyboy: PyBoy,
    syms: dict[str, int],
    item: str,
    quantity: int = 1,
) -> DialogueResult:
    """Sell an item from the bag to the mart clerk.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        item: Item name, e.g. "ANTIDOTE" (case and accents are ignored).
        quantity: How many to sell, capped at the number in the bag.
    Returns:
        The clerk's answer and the menu after it.
    """
    if quantity < 1:
        raise ValueError("Quantity must be at least 1")
    return _trade(
        pyboy=pyboy,
        syms=syms,
        action="SELL",
        item=item,
        quantity=quantity,
    )
