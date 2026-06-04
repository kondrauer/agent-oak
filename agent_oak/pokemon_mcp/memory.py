"""Memory module for the Pokemon MCP."""

from pyboy import PyBoy

from agent_oak.pokemon_mcp.mappings import (
    BADGES,
    HMs,
    Items,
    Maps,
    PokemonSpecies,
    StatusFlags,
    Tilesets,
    TMs,
)
from agent_oak.pokemon_mcp.models import (
    BagItems,
    Item,
    ObtainedBadge,
    ObtainedBadges,
    PlayerLocation,
    Pokemon,
    PokemonStats,
)

PARTY_STRUCT_LEN = 0x2C  # 44
NAME_LEN = 11


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
        if b == 0x50:  # End of string
            break
        if b == 0x7F:  # Whitespace
            out.append(" ")
        elif 0x80 <= b <= 0x99:  # Uppercase letters
            out.append(chr(b - 0x80 + ord("A")))
        elif 0xA0 <= b <= 0xB9:  # Lowercase letters
            out.append(chr(b - 0xA0 + ord("a")))
        elif 0xF6 <= b <= 0xFF:  # Digits
            out.append(chr(b - 0xF6 + ord("0")))
        else:
            out.append("?")

    return "".join(out)


def parse_pokemon(
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
        species=PokemonSpecies(species),
        nickname=decode_text(nickname),
        original_trainer=decode_text(original_trainer),
        original_trainer_id=u16_big_endian(data, 0x0C),
        level=data[0x21],
        hp=u16_big_endian(data, 0x01),
        max_hp=u16_big_endian(data, 0x22),
        status=StatusFlags(data[0x04]),
        type1=data[0x05],
        type2=data[0x06],
        moves=list(data[0x08:0x0C]),
        pp=list(data[0x1D:0x21]),
        stats=PokemonStats(
            attack=u16_big_endian(data, 0x14),
            defense=u16_big_endian(data, 0x15),
            speed=u16_big_endian(data, 0x16),
            special=u16_big_endian(data, 0x17),
        ),
        experience=(data[0x0E] << 16) | (data[0x0F] << 8) | data[0x10],
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
        party.append(parse_pokemon(pokemon, nickname, original_trainer))
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
        map_name=Maps(map_id).name,
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


def _item_name(item_id: int) -> str:
    """Get the name of an item given its ID.

    Args:
        item_id: The ID of the item to get the name of.
    Returns:
        The name of the item with the given ID.
    """
    if 0xC9 <= item_id <= 0xFF:
        return f"TM{item_id - 0xC8:02d}_{TMs(item_id)}"
    elif 0xC4 <= item_id <= 0xC8:
        return f"HM{item_id - 0xC3:02d}_{HMs(item_id)}"
    elif item_id in Items._value2member_map_:
        return Items(item_id).name
    else:
        return f"Unknown_{item_id:02X}"


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
