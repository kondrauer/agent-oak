"""Mappings for Pokemon MCP server."""

from enum import Enum

BADGES = [
    ("boulder", "Brock", "Pewter City"),
    ("cascade", "Misty", "Cerulean City"),
    ("thunder", "Lt. Surge", "Vermilion City"),
    ("rainbow", "Erika", "Celadon City"),
    ("soul", "Koga", "Fuchsia City"),
    ("marsh", "Sabrina", "Saffron City"),
    ("volcano", "Blaine", "Cinnabar Island"),
    ("earth", "Giovanni", "Viridian City"),
]

TILESET_BASE = {
    0: "overworld",
    1: "reds_house",
    2: "pokecenter",
    3: "forest",
    4: "reds_house",
    5: "gym",
    6: "pokecenter",
    7: "gym",
    8: "house",
    9: "gate",
    10: "gate",
    11: "underground",
    12: "gate",
    13: "ship",
    14: "ship_port",
    15: "cemetery",
    16: "interior",
    17: "cavern",
    18: "lobby",
    19: "mansion",
    20: "lab",
    21: "club",
    22: "facility",
    23: "plateau",
}


class BattleType(int, Enum):
    """Battle type enumeration."""

    WILD = 0
    TRAINER = 1


class PokemonTypes(int, Enum):
    """Pokemon type enumeration from Pokemon Red type constants."""

    NORMAL = 0x00
    FIGHTING = 0x01
    FLYING = 0x02
    POISON = 0x03
    GROUND = 0x04
    ROCK = 0x05
    BUG = 0x07
    GHOST = 0x08
    FIRE = 0x14
    WATER = 0x15
    GRASS = 0x16
    ELECTRIC = 0x17
    PSYCHIC = 0x18
    ICE = 0x19
    DRAGON = 0x1A


class Tilesets(int, Enum):
    """Tileset id enumeration."""

    OVERWORLD = 0x00
    REDS_HOUSE_1 = 0x01
    MART = 0x02
    FOREST = 0x03
    REDS_HOUSE_2 = 0x04
    DOJO = 0x05
    POKECENTER = 0x06
    GYM = 0x07
    HOUSE = 0x08
    FOREST_GATE = 0x09
    MUSEUM = 0x0A
    UNDERGROUND = 0x0B
    GATE = 0x0C
    SHIP = 0x0D
    SHIP_PORT = 0x0E
    CEMETERY = 0x0F
    INTERIOR = 0x10
    CAVERN = 0x11
    LOBBY = 0x12
    MANSION = 0x13
    LAB = 0x14
    CLUB = 0x15
    FACILITY = 0x16
    PLATEAU = 0x17


class StatusFlags(int, Enum):
    """Status flags enumeration."""

    NONE = 0x00
    POISONED = 0x08
    BURNED = 0x10
    FROZEN = 0x20
    PARALYZED = 0x40
    SLEEP_MASK = 0x07
