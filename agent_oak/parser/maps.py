"""Parse map blk files."""

import pprint
import re
from collections import defaultdict
from pathlib import Path

from agent_oak.memory.mappings import TILESET_BASE, Tilesets
from agent_oak.parser.models import (
    SHORE_TILES,
    SPRITE_FACING,
    WATER_TILE,
    Connection,
    Direction,
    ElevatorFloor,
    GameMap,
    GameMapConstant,
    ItemBall,
    MapObject,
    Npc,
    Sign,
    StaticMon,
    Tileset,
    Trainer,
    Warp,
)

_RE_MAP_CONST_COMPLETE = re.compile(
    pattern=r"^\s*map_const\s+(\w+),\s*(\d*),\s*(\d*)\s*;\s*\$([\w\d]{2})",
    flags=re.IGNORECASE,
)


def _classify_map_object(args: list[str]) -> MapObject:
    x, y, sprite, move, facing, text = args[:6]
    base = dict(
        x=int(x),
        y=int(y),
        sprite=sprite,
        movement=move,
        facing=facing,
        text_id=text,
    )
    match args[6:]:
        case []:
            return Npc(**base)  # ty: ignore
        case [item]:
            return ItemBall(**base, item=item)  # ty: ignore
        case [a, b] if a.startswith("OPP_"):
            return Trainer(**base, trainer_class=a, trainer_num=int(b))  # ty: ignore
        case [a, b]:
            return StaticMon(**base, species=a, level=int(b))  # ty: ignore
    raise ValueError(args)


def parse_maps(
    map_constants: Path = Path("constants/map_constants.asm"),
    map_headers_folder: Path = Path("data/maps/headers"),
    map_objects_folder: Path = Path("data/maps/objects"),
) -> tuple[dict[str, GameMap], dict[int, GameMap]]:
    """Parse all informations about maps available."""
    consts: dict[str, GameMapConstant] = {}

    with map_constants.open() as file:
        for line in file.readlines():
            if match := _RE_MAP_CONST_COMPLETE.match(line):
                name = match.group(1)
                idx = int(match.group(4), 16)
                width = int(match.group(2))
                height = int(match.group(3))

                consts[name] = GameMapConstant(
                    const=name,
                    idx=idx,
                    width=width,
                    height=height,
                )

    last_map = GameMap(
        const="LAST_MAP",
        idx=0xFF,
        label="any.blk",
        tileset="any",
        blocks=b"",
        width=0,
        height=0,
    )

    maps_by_name: dict[str, GameMap] = {"LAST_MAP": last_map}
    maps_by_id: dict[int, GameMap] = {255: last_map}

    map_header_files = sorted(map_headers_folder.glob(pattern="*"))

    for map_header_file in map_header_files:
        connections: list[Connection] = []
        warps: list[Warp] = []
        signs: list[Sign] = []
        map_objects: list[MapObject] = []
        object_names: list[str] = []

        with map_header_file.open() as file:
            map_header_line = file.readline().strip()
            label, const, tileset = (
                map_header_line.replace(
                    "map_header",
                    "",
                )
                .replace(" ", "")
                .split(",")
            )

            # the unused UndergroundPathRoute7Copy reuses the const of the
            # real map, keep the first (real) one
            if const in maps_by_name:
                continue

            blk_path = Path(f"maps/{label}.blk")
            try:
                with blk_path.open(mode="rb") as blk_file:
                    data = blk_file.read()
            except FileNotFoundError:
                print(f"No blk-File found for {const}, looked for {label}")
                data = b""

            for line in file.readlines():
                line = line.split(";", 1)[0].strip()
                if line.startswith("connection"):
                    direction, target_label, target_const, offset = (
                        line.replace(
                            "connection",
                            "",
                        )
                        .replace(" ", "")
                        .split(",")
                    )

                    connections.append(
                        Connection(
                            direction=Direction(direction),
                            target_const=target_const,
                            target_label=target_label,
                            offset=int(offset),
                        )
                    )

        with (map_objects_folder / f"{label}.asm").open() as file:
            for line in file.readlines():
                line = line.split(";", 1)[0].strip()

                if line.startswith("const_export"):
                    # one per object_event, in the same order
                    object_names.append(line.replace("const_export", "").strip())
                elif line.startswith("warp_event"):
                    x, y, dest_map, dest_warp = (
                        line.replace(
                            "warp_event",
                            "",
                        )
                        .replace(" ", "")
                        .split(",")
                    )

                    warps.append(
                        Warp(
                            x=int(x),
                            y=int(y),
                            dest_map=dest_map,
                            dest_warp=int(dest_warp),
                        )
                    )
                elif line.startswith("bg_event"):
                    x, y, text_id = (
                        line.replace(
                            "bg_event",
                            "",
                        )
                        .replace(" ", "")
                        .split(",")
                    )

                    signs.append(
                        Sign(
                            x=int(x),
                            y=int(y),
                            text_id=text_id,
                        )
                    )
                elif line.startswith("object_event"):
                    args = (
                        line.replace(
                            "object_event",
                            "",
                        )
                        .replace(" ", "")
                        .split(",")
                    )
                    map_object = _classify_map_object(args=args)
                    map_objects.append(map_object)

        for map_object, name in zip(map_objects, object_names):
            map_object.name = name

        map_const = consts[const]

        game_map = GameMap(
            const=map_const.const,
            idx=map_const.idx,
            width=map_const.width,
            height=map_const.height,
            label=label,
            tileset=tileset,
            blocks=data,
            connections=connections,
            warps=warps,
            map_objects=map_objects,
            signs=signs,
        )

        maps_by_name[const] = game_map
        maps_by_id[map_const.idx] = game_map

    for label, floors in parse_elevator_floors().items():
        elevator = next((m for m in maps_by_name.values() if m.label == label), None)
        if elevator is not None:
            elevator.elevator_floors = floors

    return maps_by_name, maps_by_id


_RE_ELEVATOR_WARP = re.compile(r"^\s*db\s+(\d+)\s*,\s*(\w+)")


def parse_elevator_floors(
    scripts: Path = Path("scripts"),
) -> dict[str, list[ElevatorFloor]]:
    """Parse the floors of every elevator, keyed by the elevator map's label.

    An elevator's warps lead wherever its menu sends the player, the map
    script copies <Label>WarpMaps (warp number, map) into wElevatorWarpMaps.
    """
    floors: dict[str, list[ElevatorFloor]] = {}
    for path in sorted(scripts.glob("*Elevator.asm")):
        label = path.stem
        in_table = False
        for line in path.read_text().splitlines():
            code = line.split(";", 1)[0].strip()
            if code == f"{label}WarpMaps:":
                in_table = True
            elif in_table and (m := _RE_ELEVATOR_WARP.match(code)):
                floors.setdefault(label, []).append(
                    ElevatorFloor(dest_map=m.group(2), dest_warp=int(m.group(1)))
                )
            elif in_table and code.endswith(":"):
                break
    return floors


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def search_maps(
    maps_by_name: dict[str, GameMap],
    query: str,
) -> list[GameMap]:
    """Find maps whose const or label contains 'query'.

    Case, spaces, underscores and apostrophes are ignored, so "oak's lab",
    "OAKS_LAB" and "OaksLab" all match OAKS_LAB.
    """
    needle = _normalize(query)
    return [
        m
        for const, m in maps_by_name.items()
        if const != "LAST_MAP"
        and (needle in _normalize(const) or needle in _normalize(m.label))
    ]


def parse_pair_collision_tile_ids(
    pair_collision_tile_ids: Path = Path("data/tilesets/pair_collision_tile_ids.asm"),
) -> tuple[dict[str, set[frozenset[int]]], dict[str, set[frozenset[int]]]]:
    """Parse pair collision tile ids."""
    land_pair_collision_tile_ids_by_name: dict[str, set[frozenset[int]]] = defaultdict(
        set
    )
    water_pair_collision_tile_ids_by_name: dict[str, set[frozenset[int]]] = defaultdict(
        set
    )

    with pair_collision_tile_ids.open() as file:
        land = True

        for line in file.readlines():
            line = line.strip()
            if line.startswith("db") and "-1" not in line:
                line = line.replace("db", "").strip()
                name, idx_1, idx_2 = line.split(",")
                idx_1 = idx_1.replace("$", "")
                idx_2 = idx_2.replace("$", "")
                if land:
                    land_pair_collision_tile_ids_by_name[name].add(
                        frozenset(
                            (
                                int(
                                    idx_1,
                                    base=16,
                                ),
                                int(
                                    idx_2,
                                    base=16,
                                ),
                            )
                        )
                    )
                else:
                    water_pair_collision_tile_ids_by_name[name].add(
                        frozenset(
                            (
                                int(
                                    idx_1,
                                    base=16,
                                ),
                                int(
                                    idx_2,
                                    base=16,
                                ),
                            )
                        )
                    )
            elif line.startswith("TilePairCollisionsWater::"):
                land = False

    return land_pair_collision_tile_ids_by_name, water_pair_collision_tile_ids_by_name


def parse_water_tilesets(
    water_tilesets: Path = Path("data/tilesets/water_tilesets.asm"),
) -> list[str]:
    """Parset water tileset names."""
    water_tilesets_names: list[str] = []

    with water_tilesets.open() as file:
        for line in file.readlines():
            line = line.strip()
            if line.startswith("db") and "-1" not in line:
                line = line.replace("db", "").strip()
                water_tilesets_names.append(line)

    return water_tilesets_names


def parse_tileset_headers(
    tileset_headers: Path = Path("data/tilesets/tileset_headers.asm"),
) -> dict[str, tuple[set[int], int | None]]:
    """Parse counter tiles and grass tile per tileset.

    Keys are lowercased names without underscores, e.g. "redshouse1".
    """
    headers: dict[str, tuple[set[int], int | None]] = {}

    with tileset_headers.open() as file:
        for line in file.readlines():
            line = line.strip()
            if not line.startswith("tileset "):
                continue
            # name, 3 counter tiles, grass tile, animations; -1 means none
            name, *values = [
                v.strip() for v in line.replace("tileset", "", 1).split(",")
            ]
            tiles = [None if v == "-1" else int(v.lstrip("$"), 16) for v in values[:4]]
            headers[name.lower()] = ({t for t in tiles[:3] if t is not None}, tiles[3])

    return headers


def parse_ledge_tile_ids(
    ledge_tiles: Path = Path("data/tilesets/ledge_tiles.asm"),
) -> list[tuple[Direction, int, int]]:
    """Parse ledge tile id pairs."""
    ledge_tiles_list: list[tuple[Direction, int, int]] = []

    with ledge_tiles.open() as file:
        for line in file.readlines():
            line = line.strip()
            if line.startswith("db") and "-1" not in line:
                line = line.replace("db", "").strip()
                sprite_dir, idx_1, idx_2, press_dir = line.split(",")
                dir = SPRITE_FACING[sprite_dir]
                idx_1 = int(idx_1.replace("$", "").strip(), base=16)
                idx_2 = int(idx_2.replace("$", "").strip(), base=16)

                ledge_tiles_list.append((dir, idx_1, idx_2))

    return ledge_tiles_list


def parse_collision_tile_ids(
    collision_tile_ids: Path = Path("data/tilesets/collision_tile_ids.asm"),
) -> dict[str, set[int]]:
    """Parse collision tile ids into Tileset->ids mapping."""
    collision_tile_ids_by_name: dict[str, set[int]] = {}

    temp: list[str] = []

    with collision_tile_ids.open() as file:
        for line in file.readlines():
            line = line.split(";", 1)[0].strip()
            if not line:
                continue

            if line.endswith("::"):
                temp.append(line[:-2].removesuffix("_Coll"))
            elif line.startswith("coll_tiles"):
                tiles = {
                    int(h, 16)
                    for h in re.findall(
                        pattern=r"\$([0-9a-fA-F]+)",
                        string=line,
                    )
                }
                for label in temp:
                    collision_tile_ids_by_name[label.lower()] = tiles

                temp.clear()

    return collision_tile_ids_by_name


def parse_cut_tree_tiles(
    cut: Path = Path("engine/overworld/cut.asm"),
) -> dict[str, set[int]]:
    """Parse the tiles Cut works on per tileset from UsedCut.

    UsedCut compares wCurMapTileset (`and a` for OVERWORLD, `cp GYM`) and
    then the tile in front of the player against the cut tree tiles, the
    ones commented "cut tree". Grass can be cut too but is walkable anyway.
    """
    trees: dict[str, set[int]] = defaultdict(set)
    tileset: str | None = None
    for line in cut.read_text().splitlines():
        code, _, comment = line.partition(";")
        code = code.strip()
        if code.startswith("UsedCut:") or code == ".nothingToCut":
            tileset = None
        if code == ".overworld" or (code == "and a" and "OVERWORLD" in comment):
            tileset = "OVERWORLD"
        elif m := re.fullmatch(r"cp\s+([A-Z_]+)", code):
            tileset = m.group(1)
        elif (m := re.fullmatch(r"cp\s+\$([0-9A-Fa-f]+)", code)) and tileset:
            if "cut tree" in comment:
                trees[tileset].add(int(m.group(1), 16))
    return dict(trees)


def load_blocksets(
    blocksets_path: Path = Path("gfx/blocksets/"),
) -> dict[str, bytes]:
    """Load all blocksets in a given path."""
    file_paths = blocksets_path.glob(pattern="*")

    blocksets_by_name: dict[str, bytes] = {}

    for path in file_paths:
        with path.open("rb") as file:
            blocksets_by_name[path.stem] = file.read()

    return blocksets_by_name


def parse_tilesets() -> tuple[dict[str, Tileset], dict[int, Tileset]]:
    """Parse every tileset."""
    blocksets = load_blocksets()
    collision_tile_ids = parse_collision_tile_ids()
    ledge_tiles = parse_ledge_tile_ids()
    water_tilesets = parse_water_tilesets()
    pair_collisions_land, pair_collisions_water = parse_pair_collision_tile_ids()
    headers = parse_tileset_headers()
    cut_trees = parse_cut_tree_tiles()

    tilesets_by_name: dict[str, Tileset] = {}
    tilesets_by_id: dict[int, Tileset] = {}

    for tileset in Tilesets:
        name = tileset.name
        idx = tileset.value

        blockset = TILESET_BASE[idx]

        water: set[int] = set()
        if name in water_tilesets:
            water = {WATER_TILE}
            if name != "SHIP_PORT":
                water |= SHORE_TILES

        counter_tiles, grass_tile = headers[name.replace("_", "").lower()]
        tileset = Tileset(
            name=name,
            blocks=blocksets[blockset],
            collision=collision_tile_ids[name.replace("_", "").lower()],
            counter_tiles=counter_tiles,
            cut_trees=cut_trees.get(name, set()),
            grass_tile=grass_tile,
            water=water,
            pair_collisions_land=pair_collisions_land[name],
            pair_collisions_water=pair_collisions_water[name],
            ledges=ledge_tiles,
        )

        tilesets_by_name[name] = tileset
        tilesets_by_id[idx] = tileset

    return tilesets_by_name, tilesets_by_id


if __name__ == "__main__":
    pprint.pprint(parse_tilesets())
