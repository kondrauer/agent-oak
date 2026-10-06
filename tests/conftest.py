"""Shared fixtures: the constant tables, the maps and synthetic RAM."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_oak.memory.read import PARTY_STRUCT_LEN
from agent_oak.objectives.constants import load_constants_json
from agent_oak.objectives.ram import BAG_CAPACITY, PARTY_LENGTH, PC_ITEM_CAPACITY, Ram
from agent_oak.parser.maps import parse_maps
from agent_oak.parser.models import GameMap
from agent_oak.pyboy_mcp.emulator import load_symbols

MakeRam = Callable[..., Ram]


@pytest.fixture(scope="session")
def constants() -> dict[str, Any]:
    """Load the tables of data/constants.json."""
    return load_constants_json()


@pytest.fixture(scope="session")
def maps() -> dict[str, GameMap]:
    """Parse every map, keyed by const."""
    return parse_maps()[0]


def _bits(indices: list[int], length: int) -> bytes:
    out = bytearray(length)
    for i in indices:
        out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def _item_list(items: dict[int, int], capacity: int) -> bytes:
    out = bytearray([len(items)])
    for item, quantity in items.items():
        out += bytes([item, quantity])
    out.append(0xFF)
    return bytes(out.ljust(1 + 2 * capacity + 1, b"\x00"))


@pytest.fixture(scope="session")
def make_ram(constants: dict[str, Any]) -> MakeRam:
    """Build Ram snapshots from names, e.g. events=["EVENT_X"]."""

    def make(
        events: tuple[str, ...] = (),
        badges: tuple[str, ...] = (),
        towns: tuple[str, ...] = (),
        hidden: tuple[str, ...] = (),
        bag: dict[str, int] | None = None,
        box: dict[str, int] | None = None,
        party: list[tuple[int, list[str]]] | None = None,
    ) -> Ram:
        """Party entries are (level, moves)."""
        c = constants
        mons = bytearray()
        for level, moves in party or []:
            mon = bytearray(PARTY_STRUCT_LEN)
            mon[0x08 : 0x08 + len(moves)] = bytes(c["moves"][m] for m in moves)
            mon[0x21] = level
            mons += mon
        count = len(party or [])
        party_head = bytes([count]) + bytes(PARTY_LENGTH + 1)
        return Ram(
            data={
                "wEventFlags": _bits(
                    [c["events"][e] for e in events], (c["num_events"] + 7) // 8
                ),
                "wObtainedBadges": _bits([c["badges"][b] for b in badges], 1),
                "wTownVisitedFlag": _bits([c["towns"][t] for t in towns], 2),
                "wToggleableObjectFlags": _bits(
                    [c["toggles"][t]["index"] for t in hidden], 32
                ),
                "wNumBagItems": _item_list(
                    {c["items"][k]: v for k, v in (bag or {}).items()}, BAG_CAPACITY
                ),
                "wNumBoxItems": _item_list(
                    {c["items"][k]: v for k, v in (box or {}).items()},
                    PC_ITEM_CAPACITY,
                ),
                "wPartyCount": party_head
                + bytes(mons).ljust(PARTY_LENGTH * PARTY_STRUCT_LEN, b"\x00"),
            },
            party_mon_offset=len(party_head),
        )

    return make


ROM = Path("pokemon-red.gb")
SAVE_AFTER_BROCK = Path("pokemon-red.gb.state")


@pytest.fixture(scope="session")
def ram_after_brock(constants: dict[str, Any]) -> Ram:
    """RAM of the save after beating Brock, needs the ROM and the state file.

    Neither is in git, the test is skipped without them.
    """
    if not (ROM.exists() and SAVE_AFTER_BROCK.exists()):
        pytest.skip("needs pokemon-red.gb and pokemon-red.gb.state in the repo root")
    from pyboy import PyBoy

    pyboy = PyBoy(str(ROM), window="null", sound_emulated=False)
    try:
        with SAVE_AFTER_BROCK.open("rb") as f:
            pyboy.load_state(f)
        return Ram.read(
            pyboy=pyboy,
            syms=load_symbols(Path("pokered.sym")),
            num_events=constants["num_events"],
        )
    finally:
        pyboy.stop(save=False)
