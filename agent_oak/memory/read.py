"""Memory module for the Pokemon MCP."""

from pathlib import Path
from typing import Literal

from pyboy import PyBoy

from agent_oak.memory.mappings import (
    BADGES,
    PokemonTypes,
    StatusFlags,
    Tilesets,
)
from agent_oak.memory.models import (
    BagItems,
    BattlePokemon,
    BattleState,
    BattleType,
    Item,
    MapObjects,
    Menu,
    Npc,
    NpcInfo,
    ObtainedBadge,
    ObtainedBadges,
    PlayerLocation,
    Pokemon,
    PokemonStats,
    TextState,
    Warp,
)
from agent_oak.parser.constants import by_id
from agent_oak.parser.models import Direction, GameMap

PARTY_STRUCT_LEN = 44
NAME_LEN = 11
TILEMAP_WIDTH = 20
TILEMAP_HEIGHT = 18
CURSOR_TILE = 0xED
IDLE_CURSOR_TILE = 0xEC  # ▷, marks the entry a menu came from
# cursor position -> option of the 2x2 FIGHT / PKMN / ITEM / RUN menu
BATTLE_MENU_CURSOR = {(9, 14): 0, (15, 14): 1, (9, 16): 2, (15, 16): 3}
CONTINUE_ARROW_TILE = 0xEE
SPACE_TILE = 0x7F
BORDER_TILE = 0x7C  # │
# corners of the text box along the bottom of the screen, (x, y): tile
TEXT_BOX_CORNERS = {(0, 12): 0x79, (19, 12): 0x7B, (0, 17): 0x7D, (19, 17): 0x7E}
TEXT_BOX_ROWS = range(13, 17)
# Pokedex entry (new catch, starter): frame corner and the divider row
DEX_ENTRY_TILES = {(0, 0): 0x63, (0, 9): 0x68}
# name and category next to the picture, then the description below
DEX_ENTRY_ROWS = ((2, 1, 19), (4, 1, 19), *((y, 1, 19) for y in range(10, 17)))
CONTINUE_ARROW_POS = (18, 16)
# sprite facing byte, SPRITESTATEDATA1_FACINGDIRECTION
FACING = {
    0x0: Direction.SOUTH,
    0x4: Direction.NORTH,
    0x8: Direction.WEST,
    0xC: Direction.EAST,
}
WY_HIDDEN = 0x90  # hWY value when no textbox/menu window is being drawn
SPRITE_STRUCT_LEN = 0x10
MAX_SPRITES = 16  # slot 0 is the player

SPECIES = by_id(Path("constants/pokemon_constants.asm"))
MOVES = by_id(Path("constants/move_constants.asm"))
ITEMS = by_id(Path("constants/item_constants.asm"))
CHARMAP = by_id(Path("constants/charmap.asm"))

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


def read_is_dialogue_open(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if a dialogue box or menu window is currently open.

    Reads hWY, the shadow copy of the window Y-position register, instead
    of decoding wTileMap: the tilemap buffer can retain stale text bytes
    from an earlier, now-closed dialogue, which would otherwise be
    misread as an open textbox. hWY sits at WY_HIDDEN whenever the window
    layer is pushed off-screen, and at a lower value whenever a
    dialogue/menu window is actually being drawn.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a dialogue/menu box is open, False otherwise.
    """
    return pyboy.memory[syms["hWY"]] != WY_HIDDEN


def read_in_battle(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if the player is currently in a battle.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a battle is in progress, False otherwise.
    """
    return pyboy.memory[syms["wIsInBattle"]] != 0


def _read_tile_map(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bytes:
    base = syms["wTileMap"]
    return bytes(pyboy.memory[base : base + TILEMAP_WIDTH * TILEMAP_HEIGHT])


def _tile(
    tiles: bytes,
    x: int,
    y: int,
) -> int:
    return tiles[y * TILEMAP_WIDTH + x]


def _decode_row(
    tiles: bytes,
    y: int,
    x0: int = 0,
    x1: int = TILEMAP_WIDTH,
) -> str:
    row = tiles[y * TILEMAP_WIDTH + x0 : y * TILEMAP_WIDTH + x1]
    # 0x00 would end decode_text early, it is a graphics tile here
    return decode_text(bytes(SPACE_TILE if b == 0 else b for b in row))


def _menu_column(tiles: bytes, x: int, y: int) -> list[tuple[int, str]]:
    """Options of the box the cursor at (x, y) is in, as (row, text).

    Walks up and down the cursor column until a box border, every row with
    text right of the column is an option. Works for any row spacing.
    """
    in_box = {SPACE_TILE, CURSOR_TILE, IDLE_CURSOR_TILE}
    top = y
    while top > 0 and _tile(tiles, x, top - 1) in in_box:
        top -= 1
    bottom = y
    while bottom < TILEMAP_HEIGHT - 1 and _tile(tiles, x, bottom + 1) in in_box:
        bottom += 1

    options = []
    for row_y in range(top, bottom + 1):
        end = next(
            (
                col
                for col in range(x + 1, TILEMAP_WIDTH)
                if _tile(tiles, col, row_y) == BORDER_TILE
            ),
            TILEMAP_WIDTH,
        )
        text = _decode_row(tiles, row_y, x + 1, end).strip()
        if text:
            options.append((row_y, text))
    return options


def _read_menu(
    pyboy: PyBoy,
    syms: dict[str, int],
    tiles: bytes,
) -> Menu | None:
    """Read the menu under the ▶ cursor, if one is shown.

    Menu RAM keeps its values after a menu closes and its layout differs per
    menu (the move list counts from 1, the battle menu keeps the column in
    wTopMenuItemX), so options and selection are read from the screen.
    """
    cursors = [
        divmod(i, TILEMAP_WIDTH)[::-1] for i, t in enumerate(tiles) if t == CURSOR_TILE
    ]
    if not cursors:
        return None
    x, y = cursors[0]

    if read_in_battle(pyboy=pyboy, syms=syms):
        if "FIGHT" in _decode_row(tiles, 14) and (x, y) in BATTLE_MENU_CURSOR:
            return Menu(
                kind="battle_menu",
                options=["FIGHT", "PKMN", "ITEM", "RUN"],
                selected=BATTLE_MENU_CURSOR[(x, y)],
            )
        move_menu = "TYPE/" in _decode_row(tiles, 9)
    else:
        move_menu = False

    if x == 0:
        # party menu: cursor left of the HP bar, name one row above it
        count = pyboy.memory[syms["wPartyCount"]]
        return Menu(
            kind="party_menu",
            options=[_decode_row(tiles, 2 * i, 3, 13).strip() for i in range(count)],
            selected=(y - 1) // 2,
        )

    options = _menu_column(tiles=tiles, x=x, y=y)
    rows = [row_y for row_y, _ in options]
    return Menu(
        kind="move_menu" if move_menu else "menu",
        options=[text for _, text in options],
        selected=rows.index(y) if y in rows else 0,
    )


def read_text_state(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> TextState:
    """Read what the text box at the bottom of the screen shows.

    A Pokedex entry counts as an open box too, it waits for A the same way.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
    Returns:
        Whether the box is open, its lines, whether the game waits for A
            (continue arrow) and the menu waiting for a choice, if any.
    """
    tiles = _read_tile_map(pyboy=pyboy, syms=syms)
    if all(_tile(tiles, x, y) == t for (x, y), t in TEXT_BOX_CORNERS.items()):
        rows = [(y, 1, TILEMAP_WIDTH - 1) for y in TEXT_BOX_ROWS]
    elif all(_tile(tiles, x, y) == t for (x, y), t in DEX_ENTRY_TILES.items()):
        rows = list(DEX_ENTRY_ROWS)
    else:
        rows = []

    box_open = bool(rows)
    text = []
    for y, x0, x1 in rows:
        line = _decode_row(tiles, y, x0, x1).replace("▼", "").strip()
        if line:
            text.append(line)
    return TextState(
        box_open=box_open,
        text=text,
        waiting_for_a=box_open
        and _tile(tiles, *CONTINUE_ARROW_POS) == CONTINUE_ARROW_TILE,
        menu=_read_menu(pyboy=pyboy, syms=syms, tiles=tiles),
    )


def read_player_facing(pyboy: PyBoy, syms: dict[str, int]) -> Direction | None:
    """Read the direction the player is facing."""
    return FACING.get(pyboy.memory[syms["wSpritePlayerStateData1FacingDirection"]])


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


def read_warps(pyboy: PyBoy, syms: dict[str, int]) -> list[Warp]:
    """Read current warps."""
    count = pyboy.memory[syms["wNumberOfWarps"]]
    base = syms["wWarpEntries"]
    warps = []
    for i in range(count):
        y, x, dest_warp, dest_map = pyboy.memory[base + i * 4 : base + i * 4 + 4]

        if dest_map == 0xFF:
            actual_dest_map = pyboy.memory[syms["wLastMap"]]
        else:
            actual_dest_map = dest_map

        warps.append(
            Warp(
                x=x,
                y=y,
                dest_warp=dest_warp,
                dest_map=actual_dest_map,
            )
        )
    return warps


def read_npcs(pyboy: PyBoy, syms: dict[str, int]) -> list[Npc]:
    """Read current NPCs."""
    count = pyboy.memory[syms["wNumSprites"]]
    data1 = syms["wSprite01StateData1"]
    data2 = syms["wSprite01StateData2"]

    npcs = []
    for i in range(min(count, MAX_SPRITES - 1)):
        s1 = data1 + i * SPRITE_STRUCT_LEN
        s2 = data2 + i * SPRITE_STRUCT_LEN

        if pyboy.memory[s1 + 0x00] == 0:  # picture id 0 = empty slot
            continue
        if pyboy.memory[s1 + 0x02] == 0xFF:  # image index $FF = hidden
            continue

        npcs.append(
            Npc(
                slot=i + 1,
                y=pyboy.memory[s2 + 0x04] - 4,  # SPRITESTATEDATA2_MAPY
                x=pyboy.memory[s2 + 0x05] - 4,  # SPRITESTATEDATA2_MAPX
                facing=pyboy.memory[s1 + 0x09],  # 0 down, 4 up, 8 left, $C right
            )
        )
    return npcs


def read_map_objects(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
) -> MapObjects:
    """Read the NPCs and signs of the current map.

    Sprite slot n is the n-th object_event of the map header, so live
    positions are joined with the static object data by slot.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
        maps_by_id: Mapping of GameMaps to respective id.
    Returns:
        The visible NPCs with their current position and the map's signs.
    """
    game_map = maps_by_id[pyboy.memory[syms["wCurMap"]]]
    npcs = [
        NpcInfo(
            slot=npc.slot,
            x=npc.x,
            y=npc.y,
            facing=FACING.get(npc.facing),
            object=(
                game_map.map_objects[npc.slot - 1]
                if npc.slot <= len(game_map.map_objects)
                else None
            ),
        )
        for npc in read_npcs(pyboy=pyboy, syms=syms)
    ]
    return MapObjects(map=game_map.const, npcs=npcs, signs=game_map.signs)


def read_location(
    pyboy: PyBoy,
    syms: dict[str, int],
    maps_by_id: dict[int, GameMap],
) -> PlayerLocation:
    """Read the player's location from the emulator's memory.

    Args:
        pyboy: The emulator instance to read from.
        syms: The symbol table mapping names to addresses.
        maps_by_id: Mapping of GameMaps to respective id.
    Returns:
        A PlayerLocation object representing the player's location.
    """
    map_id = pyboy.memory[syms["wCurMap"]]
    tileset_id = pyboy.memory[syms["wCurMapTileset"]]
    return PlayerLocation(
        map_id=map_id,
        map=maps_by_id[map_id],
        tileset_name=Tilesets(tileset_id).name,
        tileset_id=tileset_id,
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
