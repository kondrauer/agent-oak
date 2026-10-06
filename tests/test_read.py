"""Tests for the memory readers that need no emulator."""

from agent_oak.memory.read import _parse_pokemon, read_options

# wPartyMon1, wPartyMonNicks and wPartyMonOT of the save after Brock:
# SQUIRTLE Lv15 with TACKLE / TAIL WHIP / BUBBLE / WATER GUN
SQUIRTLE = bytes.fromhex(
    "b10023000015152d21279137fa5a0007fe036103950441044f0267280d231e17190f00270015001c00130018"
)
NICKNAME = bytes.fromhex("9290948891938b84505050")
OT = bytes.fromhex("9184835080928750898082")


class FakePyBoy:
    """Just enough of PyBoy to read bytes from memory."""

    def __init__(self, memory: dict[int, int]) -> None:
        """Back the memory with a dict, unset addresses read as 0."""
        self.memory = memory


def test_parse_pokemon_stats() -> None:
    """Stats are read from the big endian words at 0x24-0x2B."""
    mon = _parse_pokemon(data=SQUIRTLE, nickname=NICKNAME, original_trainer=OT)

    assert mon.species == "SQUIRTLE"
    assert mon.nickname == "SQUIRTLE"
    assert mon.original_trainer == "RED"
    assert mon.level == 15
    assert (mon.hp, mon.max_hp) == (35, 39)
    assert mon.moves == ["TACKLE", "TAIL_WHIP", "BUBBLE", "WATER_GUN"]
    assert mon.pp == [35, 30, 23, 25]
    assert mon.experience == 2046
    stats = mon.stats
    assert (stats.attack, stats.defense, stats.speed, stats.special) == (
        21,
        28,
        19,
        24,
    )


def test_read_options() -> None:
    """Text speed is the low nibble, animation off bit 7, style set bit 6."""
    syms = {"wOptions": 0xD355}

    fast_off_set = read_options(FakePyBoy({0xD355: 0xC1}), syms)  # ty:ignore[invalid-argument-type]
    medium_on_shift = read_options(FakePyBoy({0xD355: 0x03}), syms)  # ty:ignore[invalid-argument-type]

    assert fast_off_set.model_dump() == {
        "text_speed": "FAST",
        "battle_animation": "OFF",
        "battle_style": "SET",
    }
    assert medium_on_shift.model_dump() == {
        "text_speed": "MEDIUM",
        "battle_animation": "ON",
        "battle_style": "SHIFT",
    }
