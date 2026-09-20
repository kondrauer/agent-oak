"""Parse map blk files."""

import re
from pathlib import Path

from pydantic import BaseModel

_RE_MAP_CONST_COMPLETE = re.compile(
    pattern=r"^\s*map_const\s+(\w+),\s*(\d*),\s*(\d*)\s*;\s*\$(\d{2})",
    flags=re.IGNORECASE,
)


class Map(BaseModel):
    """Map datastructure."""

    name: str
    blk_name: str
    blocks: bytes
    width: int
    height: int


def _convert_to_blk_name(
    strings: list[str],
) -> str:
    """Convert a constant identifier to its .blk-file name."""
    tilecase = []

    for s in strings:
        if re.fullmatch(
            pattern=r"\d*F",
            string=s,
        ):
            tilecase.append(s)
        elif s == "SS":
            tilecase.append(s)
        elif s == "COPY":
            continue
        else:
            tilecase.append(s.title())

    return "".join(tilecase)


def parse_maps(
    map_constants: Path = Path("constants/map_constants.asm"),
) -> tuple[dict[str, Map], dict[int, Map]]:
    """Parse map_constants.asm file."""
    any_map = Map(
        name="ANY_MAP",
        blk_name="any.blk",
        blocks=b"",
        width=0,
        height=0,
    )

    maps_by_name: dict[str, Map] = {"ANY_MAP": any_map}
    maps_by_id: dict[int, Map] = {255: any_map}

    with map_constants.open() as file:
        for line in file.readlines():
            if match := _RE_MAP_CONST_COMPLETE.match(line):
                name = match.group(1)
                idx = int(match.group(4), 16)
                name_split = name.split("_")
                blk_name = _convert_to_blk_name(strings=name_split)
                blk_path = Path(f"maps/{blk_name}.blk")

                try:
                    with blk_path.open(mode="rb") as file:
                        data = file.read()

                    map = Map(
                        name=name,
                        blk_name=name,
                        blocks=data,
                        width=int(match.group(2)),
                        height=int(match.group(3)),
                    )

                    maps_by_name[name] = map
                    maps_by_id[idx] = map
                except FileNotFoundError:
                    print(f"No blk-File found for {name}, looked for {blk_name}")

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
    print(parse_maps())
