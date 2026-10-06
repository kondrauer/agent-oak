"""Tests for the assembly constant parser and data/constants.json."""

from agent_oak.objectives.constants import build_constants, load_constants_json
from agent_oak.parser.constants import parse_asm_constants

EVENTS = """
\tconst_def
\tconst EVENT_A        ; 0
\tconst_skip 2
\tconst EVENT_B        ; 3
\tconst_skip
\tconst EVENT_C        ; 5
\tconst_next $28
\tconst EVENT_D        ; $28
\tconst_next $F0 - 2
\tconst EVENT_E        ; $EE
DEF NUM_EVENTS EQU const_value
"""


def test_const_skip_and_const_next() -> None:
    """const_skip N skips N values, const_next jumps to an expression."""
    syms = parse_asm_constants(EVENTS)

    assert syms["EVENT_A"] == 0
    assert syms["EVENT_B"] == 3
    assert syms["EVENT_C"] == 5
    assert syms["EVENT_D"] == 0x28
    assert syms["EVENT_E"] == 0xEE
    assert syms["NUM_EVENTS"] == 0xEF


def test_const_def_start_and_increment() -> None:
    """const_def takes a start value and a step."""
    syms = parse_asm_constants("\tconst_def 6, 2\n\tconst A\n\tconst_skip\n\tconst B\n")

    assert syms == {"A": 6, "B": 10}


def test_macro_bodies_are_skipped() -> None:
    """Lines inside MACRO ... ENDM are not definitions."""
    text = "MACRO add_hm\n\tDEF HM_\\1 EQU const_value\n\tconst \\1\nENDM\n"
    syms = parse_asm_constants(text + "\tconst_def $C4\n\tadd_hm CUT\n", True)

    assert syms == {"HM_CUT": 0xC4}


def test_event_indices_from_the_disassembly() -> None:
    """Spot checks against event_constants.asm, counted by hand."""
    events = load_constants_json()["events"]

    assert events["EVENT_FOLLOWED_OAK_INTO_LAB"] == 0
    assert events["EVENT_GOT_TOWN_MAP"] == 0x18  # after const_skip 2, 2, 17
    assert events["EVENT_VIRIDIAN_GYM_OPEN"] == 0x28  # const_next $28
    assert events["EVENT_BEAT_BROCK"] == 0x77
    assert events["EVENT_BEAT_MISTY"] == 0xBF


def test_item_ids() -> None:
    """HMs and TMs get the disassembly's HM_ / TM_ names and ids."""
    items = load_constants_json()["items"]

    assert items["S_S_TICKET"] == 0x3F
    assert items["HM_CUT"] == 0xC4
    assert items["TM_MEGA_PUNCH"] == 0xC9
    assert items["TM_SUBSTITUTE"] == 0xFA


def test_constants_json_is_up_to_date() -> None:
    """Rerun scripts/extract_constants.py when this fails."""
    assert build_constants() == load_constants_json()
