"""Memory module for the Pokemon MCP."""

from pathlib import Path
from typing import Literal

from pyboy import PyBoy

from agent_oak.pokemon_mcp.constant_parser import by_id
from agent_oak.pokemon_mcp.mappings import (
    BADGES,
    PokemonTypes,
    StatusFlags,
    Tilesets,
)
from agent_oak.pokemon_mcp.models import (
    BagItems,
    BattlePokemon,
    BattleState,
    BattleType,
    Dialogue,
    Item,
    ObtainedBadge,
    ObtainedBadges,
    PlayerLocation,
    Pokemon,
    PokemonStats,
)

PARTY_STRUCT_LEN = 44
NAME_LEN = 11
TILEMAP_WIDTH = 20

SPECIES = by_id(Path("constants/pokemon_constants.asm"))
MOVES = by_id(Path("constants/move_constants.asm"))
ITEMS = by_id(Path("constants/item_constants.asm"))
MAPS = by_id(Path("constants/map_constants.asm"))
CHARMAP = by_id(Path("constants/charmap.asm"))
print(CHARMAP)

BattlePokemonPrefix = Literal["wBattleMon", "wEnemyMon"]


def _item_name(item_id: int) -> str:
    """Get the name of an item given its ID.

    Args:
        item_id: The ID of the item to get the name of.
    Returns:
        The name of the item with the given ID.
    """
    if 0xC9 <= item_id <= 0xFF:
        return f"TM{item_id - 0xC8:02d}_{ITEMS[item_id]}"
    elif 0xC4 <= item_id <= 0xC8:
        return f"HM{item_id - 0xC3:02d}_{ITEMS[item_id]}"
    elif item_id in ITEMS:
        return ITEMS[item_id]
    else:
        return f"Unknown_{item_id:02X}"


def _parse_pokemon(
    data: bytes,
    nickname: bytes,
    original_trainer: bytes,
) -> Pokemon:
    """Parse a Pokemon from the given data.

    Args:
        data: The raw bytes representing the Pokemon.
        nickname: The raw bytes representing the Pokemon's nickname.
        original_trainer: The raw bytes representing the Pokemon's original trainer.
    Returns:
        A Pokemon object representing the parsed data.
    """
    species = data[0]

    return Pokemon(
        species_id=species,
        species=SPECIES[species],
        nickname=decode_text(nickname),
        original_trainer=decode_text(original_trainer),
        original_trainer_id=u16_big_endian(data, 0x0C),
        level=data[0x21],
        hp=u16_big_endian(data, 0x01),
        max_hp=u16_big_endian(data, 0x22),
        status=StatusFlags(data[0x04]),
        type1=PokemonTypes(data[0x05]),
        type2=PokemonTypes(data[0x06]),
        moves=[MOVES[m] for m in data[0x08:0x0C]],
        pp=list(data[0x1D:0x21]),
        stats=PokemonStats(
            attack=u16_big_endian(data, 0x14),
            defense=u16_big_endian(data, 0x15),
            speed=u16_big_endian(data, 0x16),
            special=u16_big_endian(data, 0x17),
        ),
        experience=(data[0x0E] << 16) | (data[0x0F] << 8) | data[0x10],
    )


def _parse_battle_pokemon(
    pyboy: PyBoy,
    syms: dict[str, int],
    prefix: BattlePokemonPrefix,
    include_nick: bool,
) -> BattlePokemon:
    """Parse a Pokemon in battle from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
        prefix: The prefix for the battle Pokemon symbols.
        include_nick: Whether to include the Pokemon's nickname in the parsed data.
    Returns:
        A BattlePokemon object representing the parsed data.
    """
    species = pyboy.memory[syms[f"{prefix}Species"]]
    hp = (pyboy.memory[syms[f"{prefix}HP"]] << 8) | pyboy.memory[
        syms[f"{prefix}HP"] + 1
    ]
    max_hp = (pyboy.memory[syms[f"{prefix}MaxHP"]] << 8) | pyboy.memory[
        syms[f"{prefix}MaxHP"] + 1
    ]

    out = BattlePokemon(
        species_id=species,
        species=SPECIES[species],
        level=pyboy.memory[syms[f"{prefix}Level"]],
        hp=hp,
        max_hp=max_hp,
        status=StatusFlags(pyboy.memory[syms[f"{prefix}Status"]]),
        type1=PokemonTypes(pyboy.memory[syms[f"{prefix}Type1"]]),
        type2=PokemonTypes(pyboy.memory[syms[f"{prefix}Type2"]]),
        moves=[
            MOVES[m]
            for m in pyboy.memory[syms[f"{prefix}Moves"] : syms[f"{prefix}Moves"] + 4]
        ],
        pp=list(pyboy.memory[syms[f"{prefix}PP"] : syms[f"{prefix}PP"] + 4]),
    )

    if include_nick:
        nickname_bytes = bytes(
            pyboy.memory[syms[f"{prefix}Nick"] : syms[f"{prefix}Nick"] + NAME_LEN]
        )
        out.nickname = decode_text(nickname_bytes)

    return out


def u16_big_endian(
    data: bytes,
    off: int,
) -> int:
    """Read a big-endian 16-bit unsigned integer from the given offset.

    Args:
        data: The data to read from.
        off: The offset to read from.
    Returns:
        The 16-bit unsigned integer at the given offset.
    """
    return (data[off] << 8) | data[off + 1]


def decode_text(data: bytes) -> str:
    """Decode text from the Pokemon ROM encoding.

    Args:
        data: The bytes to decode.
    Returns:
        The decoded string.
    """
    out = []
    for b in data:
        if b == 0:
            break
        elif b in CHARMAP.keys():
            out.append(CHARMAP[b])
        else:
            out.append("")

    return "".join(out)


def decode_status(b: int) -> list[str]:
    """Decode a Pokemon's status flags from the given byte.

    Args:
        b: The byte representing the Pokemon's status flags.
    Returns:
        A list of strings representing the Pokemon's status conditions.
    """
    if b == 0:
        return ["healthy"]
    out = []
    for mask, name in StatusFlags._value2member_map_.items():
        if b & mask:
            out.append(name)
    return out


def read_dialogue_text(
    pyboy: PyBoy,
    syms: dict[str, int],
    rows: range = range(12, 18),
) -> Dialogue:
    """Read the current dialogue text from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
        rows: The range of text box rows to read from (default is 12-17).
    Returns:
        The decoded dialogue text currently displayed in the text box.
    """
    base = syms["wTileMap"]
    lines = []
    for row in rows:
        row_start = base + row * TILEMAP_WIDTH
        row_bytes = bytes(pyboy.memory[row_start : row_start + TILEMAP_WIDTH])
        decoded = decode_text(data=row_bytes).rstrip()
        if decoded:
            lines.append(decoded)
    return Dialogue(
        text="\n".join(lines),
        has_dialogue=bool(lines),
    )


def read_party(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> list[Pokemon]:
    """Read the player's party from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        A list of Pokemon representing the player's party.
    """
    count = pyboy.memory[syms["wPartyCount"]]
    base = syms["wPartyMon1"]
    nicks = syms["wPartyMonNicks"]
    ots = syms["wPartyMonOT"]
    party = []
    for i in range(count):
        pokemon = bytes(
            pyboy.memory[
                base + i * PARTY_STRUCT_LEN : base + (i + 1) * PARTY_STRUCT_LEN
            ]
        )
        nickname = bytes(
            pyboy.memory[nicks + i * NAME_LEN : nicks + (i + 1) * NAME_LEN]
        )
        original_trainer = bytes(
            pyboy.memory[ots + i * NAME_LEN : ots + (i + 1) * NAME_LEN]
        )
        party.append(_parse_pokemon(pokemon, nickname, original_trainer))
    return party


def read_location(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> PlayerLocation:
    """Read the player's location from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        A PlayerLocation object representing the player's location.
    """
    map_id = pyboy.memory[syms["wCurMap"]]
    tileset_id = pyboy.memory[syms["wCurMapTileset"]]
    return PlayerLocation(
        map_id=map_id,
        map_name=MAPS[map_id],
        tileset=Tilesets(tileset_id).name,
        x=pyboy.memory[syms["wXCoord"]],
        y=pyboy.memory[syms["wYCoord"]],
    )


def read_badges(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> ObtainedBadges:
    """Read the player's badges from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        An ObtainedBadges object representing the player's obtained badges.
    """
    bits = pyboy.memory[syms["wObtainedBadges"]]
    obtained = [
        ObtainedBadge(
            name=name,
            leader=leader,
            city=city,
        )
        for i, (name, leader, city) in enumerate(BADGES)
        if bits & (1 << i)
    ]

    return ObtainedBadges(
        badges=obtained,
        count=len(obtained),
        raw_bits=bits,
    )


def read_bag(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> BagItems:
    """Read the player's bag from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        An Items object representing the player's bag contents.
    """
    count = pyboy.memory[syms["wNumBagItems"]]
    base = syms["wBagItems"]
    items = []

    for i in range(count):
        item_id = pyboy.memory[base + i * 2]
        qty = pyboy.memory[base + i * 2 + 1]
        items.append(
            Item(
                id=item_id,
                name=_item_name(item_id),
                quantity=qty,
            )
        )

    return BagItems(
        items=items,
        count=count,
    )


def read_battle_state(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> BattleState:
    """Read the current battle state from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        A BattleState object representing the current battle state.
    """
    in_battle = pyboy.memory[syms["wIsInBattle"]] != 0
    battle_type = (
        BattleType(pyboy.memory[syms["wBattleType"]]) if in_battle else "unknown"
    )
    player_pokemon = (
        _parse_battle_pokemon(
            pyboy,
            syms,
            "wBattleMon",
            include_nick=True,
        )
        if in_battle
        else None
    )
    enemy_pokemon = (
        _parse_battle_pokemon(
            pyboy,
            syms,
            "wEnemyMon",
            include_nick=False,
        )
        if in_battle
        else None
    )

    return BattleState(
        in_battle=in_battle,
        battle_type=battle_type,
        player_pokemon=player_pokemon,
        enemy_pokemon=enemy_pokemon,
    )
