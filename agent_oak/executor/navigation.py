"""Functions for exectuing navigation."""

from pyboy import PyBoy

from agent_oak.memory.mappings import TILESET_BASE
from agent_oak.memory.read import (
    read_in_battle,
    read_is_dialogue_open,
    read_location,
    read_npcs,
    read_warps,
)
from agent_oak.parser.maps import load_blocksets, parse_collision_tile_ids

BLOCKSETS = load_blocksets()
COLLISION_TILE_IDS = parse_collision_tile_ids()

DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WALK_HOLD_FRAMES = 12
WALK_SETTLE_FRAMES = 8
MAP_TRANSITION_SETTLE_FRAMES = 60

WATER_TILE = 0x14
CUT_TREE = {"overworld": 0x3D, "gym": 0x50}
GRASS_TILE = {"overworld": 0x52, "forest": 0x20, "plateau": 0x45}
LEDGE_SYMBOLS = {0x36: "v", 0x37: "v", 0x27: "<", 0x0D: ">", 0x1D: ">"}

# Bottom-left tile of each 2x2 quadrant inside a 4x4 block, [qy][qx]
QUADRANT_TILE = (
    (4, 6),
    (12, 14),
)


def walk_to(
    pyboy: PyBoy,
    syms: dict[str, int],
    x: int,
    y: int,
    max_steps: int = 150,
) -> dict[str, object]:
    """Walk toward (x, y) on the current map, one tile at a time.

    There is no vendored collision/warp data for the ROM, so this moves
    greedily toward the target and detects walls by checking whether the
    player's coordinates actually changed after a button press ("bump
    detection"), backing off directions that turned out to be blocked from
    a given tile. It stops as soon as the map changes (e.g. stairs or a
    door were used), the target tile is reached, a battle or dialogue
    interrupts, or no direction makes progress.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        x: The target x coordinate on the current map.
        y: The target y coordinate on the current map.
        max_steps: The maximum number of tile-moves to attempt.
    Returns:
        A dictionary containing the status
            (arrived/map_changed/interupt/stuck/timeout) and final location.
    """
    start_map = read_location(pyboy=pyboy, syms=syms).map_id
    blocked: set[tuple[int, int, str]] = set()

    for _ in range(max_steps):
        loc = read_location(pyboy=pyboy, syms=syms)

        if loc.map_id != start_map:
            # The map/coordinate bytes update in separate writes during the
            # transition, so let it fully settle before reporting location.
            for _ in range(MAP_TRANSITION_SETTLE_FRAMES):
                pyboy.tick()
            loc = read_location(pyboy=pyboy, syms=syms)
            return {"status": "map_changed", "location": loc.model_dump()}
        if loc.x == x and loc.y == y:
            return {"status": "arrived", "location": loc.model_dump()}
        if read_in_battle(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "battle",
                "location": loc.model_dump(),
            }
        if read_is_dialogue_open(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "dialogue",
                "location": loc.model_dump(),
            }

        dx, dy = x - loc.x, y - loc.y
        toward = []
        if dx > 0:
            toward.append("right")
        elif dx < 0:
            toward.append("left")
        if dy > 0:
            toward.append("down")
        elif dy < 0:
            toward.append("up")
        if abs(dy) > abs(dx):
            toward.reverse()
        # Prefer sideways detours over backtracking away from the target,
        # e.g. don't retreat "up" just because "down" is blocked.
        avoid = {OPPOSITE[d] for d in toward}
        sideways = [d for d in DIRECTIONS if d not in toward and d not in avoid]
        backtrack = [d for d in DIRECTIONS if d not in toward and d in avoid]
        order = toward + sideways + backtrack
        unblocked = [d for d in order if (loc.x, loc.y, d) not in blocked]

        moved = False
        for direction in unblocked or order:
            pyboy.button(direction, delay=WALK_HOLD_FRAMES)
            for _ in range(WALK_HOLD_FRAMES + WALK_SETTLE_FRAMES):
                pyboy.tick()
            new_loc = read_location(pyboy=pyboy, syms=syms)
            if (new_loc.map_id, new_loc.x, new_loc.y) != (loc.map_id, loc.x, loc.y):
                moved = True
                break
            blocked.add((loc.x, loc.y, direction))

        if not moved:
            return {"status": "stuck", "location": loc.model_dump()}

    return {
        "status": "timeout",
        "location": read_location(pyboy=pyboy, syms=syms).model_dump(),
    }


def goto(waypoint: str):
    """Go to a waypoint."""
    pass


def tile_symbol(tile_id: int, base: str) -> str:
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
    blocks,
    width_blocks: int,
    base: str,
) -> list[list[str]]:
    """Blocks (row-major, one byte each) -> grid of step cells, 2x2 per block."""
    blockset = BLOCKSETS[base]
    height_blocks = len(blocks) // width_blocks
    grid = [["#"] * (width_blocks * 2) for _ in range(height_blocks * 2)]

    for index, block_id in enumerate(blocks):
        block_y, block_x = divmod(index, width_blocks)
        tiles = blockset[block_id * 16 : (block_id + 1) * 16]
        for qy in range(2):
            for qx in range(2):
                tile_id = tiles[QUADRANT_TILE[qy][qx]]
                grid[block_y * 2 + qy][block_x * 2 + qx] = tile_symbol(tile_id, base)

    return grid


def render_grid(grid: list[list[str]]) -> str:
    """Render a grid as string."""
    width = len(grid[0])
    lines = ["    " + " ".join(f"{x:>2}" for x in range(width))]
    for y, row in enumerate(grid):
        lines.append(f"{y:>3} " + " ".join(f"{c:>2}" for c in row))
    return "\n".join(lines)


def render_current_map(pyboy: PyBoy, syms: dict[str, int]) -> str:
    """Render the current map as string."""
    loc = read_location(pyboy=pyboy, syms=syms)
    warps = read_warps(pyboy=pyboy, syms=syms)
    npcs = read_npcs(pyboy=pyboy, syms=syms)
    base = TILESET_BASE[loc.tileset_id]

    grid = build_grid(loc.map.blocks, loc.map.width, base)

    def place(x: int, y: int, symbol: str) -> None:
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            grid[y][x] = symbol

    for warp in warps:
        place(warp.x, warp.y, "D")
    for npc in npcs:
        place(npc.x, npc.y, "N")
    place(loc.x, loc.y, "@")

    legend = '@ you  N npc  D warp  . walkable  # blocked  " grass  ~ water  T tree  v<> ledge'  # noqa: E501
    header = f"{loc.map.name} ({len(grid[0])}x{len(grid)})  you: ({loc.x}, {loc.y})"
    return f"{header}\n{legend}\n\n{render_grid(grid)}"
