"""Parse map blk files."""

import pprint
import re
from pathlib import Path

from agent_oak.parser.models import (
    Connection,
    Direction,
    GameMap,
    GameMapConstant,
    ItemBall,
    MapObject,
    Npc,
    Sign,
    StaticMon,
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
        x=int(x), y=int(y), sprite=sprite, movement=move, facing=facing, text_id=text
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

                if line.startswith("warp_event"):
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

    return maps_by_name, maps_by_id


def parse_collision_tile_ids(
    collision_tile_ids: Path = Path("data/tilesets/collision_tile_ids.asm"),
) -> dict[str, list[int]]:
    """Parse collision tile ids into Tileset->ids mapping."""
    collision_tile_ids_by_name: dict[str, list[int]] = {}

    temp: list[str] = []

    with collision_tile_ids.open() as file:
        for line in file.readlines():
            line = line.split(";", 1)[0].strip()
            if not line:
                continue

            if line.endswith("::"):
                temp.append(line[:-2].removesuffix("_Coll"))
            elif line.startswith("coll_tiles"):
                tiles = [
                    int(h, 16)
                    for h in re.findall(
                        pattern=r"\$([0-9a-fA-F]+)",
                        string=line,
                    )
                ]
                for label in temp:
                    collision_tile_ids_by_name[label.lower()] = tiles

                temp.clear()

    return collision_tile_ids_by_name


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


if __name__ == "__main__":
    pprint.pprint(parse_maps())
