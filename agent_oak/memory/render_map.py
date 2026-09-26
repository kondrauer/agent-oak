"""Render the current map."""

from pyboy import PyBoy

from agent_oak.memory.mappings import TILESET_BASE
from agent_oak.memory.read import MAPS_BY_NAME, read_location, read_npcs
from agent_oak.parser.maps import load_blocksets, parse_collision_tile_ids
from agent_oak.parser.models import WATER_TILE

BLOCKSETS = load_blocksets()
COLLISION_TILE_IDS = parse_collision_tile_ids()

CUT_TREE = {
    "overworld": 0x3D,
    "gym": 0x50,
}
GRASS_TILE = {
    "overworld": 0x52,
    "forest": 0x20,
    "plateau": 0x45,
}
LEDGE_SYMBOLS = {
    0x36: "v",
    0x37: "v",
    0x27: "<",
    0x0D: ">",
    0x1D: ">",
}

# Bottom-left tile of each 2x2 quadrant inside a 4x4 block, [qy][qx]
QUADRANT_TILE = (
    (4, 6),
    (12, 14),
)


def _place(
    x: int,
    y: int,
    symbol: str,
    grid: list[list[str]],
) -> None:
    if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
        grid[y][x] = symbol


def tile_symbol(
    tile_id: int,
    base: str,
) -> str:
    """Map tile_id to a symbol."""
    if base == "overworld" and tile_id in LEDGE_SYMBOLS:
        return LEDGE_SYMBOLS[tile_id]
    if tile_id == WATER_TILE:
        return "~"
    if tile_id == CUT_TREE.get(base):
        return "T"
    if tile_id == GRASS_TILE.get(base):
        return '"'
    if tile_id in COLLISION_TILE_IDS[base]:
        return "."
    return "#"


def build_grid(
    blocks: bytes,
    width_blocks: int,
    base: str,
) -> tuple[list[list[str]], list[list[int]]]:
    """Blocks (row-major, one byte each) -> grid of step cells, 2x2 per block."""
    blockset = BLOCKSETS[base]
    height_blocks = len(blocks) // width_blocks
    # grid in step coordinates is 2Wx2H, as one block WxH holds 2x2 step squares
    grid_str = [["#"] * (width_blocks * 2) for _ in range(height_blocks * 2)]
    grid_id = [[-1] * (width_blocks * 2) for _ in range(height_blocks * 2)]

    for index, block_id in enumerate(blocks):
        # y = index//W, x=index%W
        block_y, block_x = divmod(
            index,
            width_blocks,
        )
        # fetch 16 tile-IDs from blockset correlating to block id
        tiles = blockset[block_id * 16 : (block_id + 1) * 16]
        for qy in range(2):
            for qx in range(2):
                # get tile id that is checked for collisions
                # (bottom left of each quadrant)
                tile_id = tiles[QUADRANT_TILE[qy][qx]]
                grid_id_x = block_x * 2 + qx
                grid_id_y = block_y * 2 + qy
                grid_str[grid_id_y][grid_id_x] = tile_symbol(
                    tile_id,
                    base,
                )

                grid_id[grid_id_y][grid_id_x] = tile_id

    return grid_str, grid_id


def render_grid(grid: list[list[str]]) -> str:
    """Render a grid as string."""
    width = len(grid[0])
    lines = ["    " + " ".join(f"{x:>2}" for x in range(width))]
    for y, row in enumerate(grid):
        lines.append(f"{y:>3} " + " ".join(f"{c:>2}" for c in row))
    return "\n".join(lines)


def render_current_map(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> str:
    """Render the current map as string."""
    loc = read_location(pyboy=pyboy, syms=syms)
    npcs = read_npcs(pyboy=pyboy, syms=syms)
    base = TILESET_BASE[loc.tileset_id]

    grid, _ = build_grid(
        blocks=loc.map.blocks,
        width_blocks=loc.map.width,
        base=base,
    )

    for warp in loc.map.warps:
        _place(
            x=warp.x,
            y=warp.y,
            symbol="D",
            grid=grid,
        )
    for npc in npcs:
        _place(
            x=npc.x,
            y=npc.y,
            symbol="N",
            grid=grid,
        )

    # render player
    _place(
        x=loc.x,
        y=loc.y,
        symbol="@",
        grid=grid,
    )

    legend = '@ you  N npc  D warp  . walkable  # blocked  " grass  ~ water  T tree  v<> ledge'  # noqa: E501
    header = f"{loc.map.const} ({len(grid[0])}x{len(grid)})  you: ({loc.x}, {loc.y})"
    warps_str = "Warps: " + " ".join(
        [
            f"({warp.x}, {warp.y}) -> {MAPS_BY_NAME[warp.dest_map].const}"
            for warp in loc.map.warps
        ]
    )

    return f"{header}\n{legend}\n{warps_str}\n{render_grid(grid)}"
