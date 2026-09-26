"""Models for parsing disassembly data."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Direction(str, Enum):
    """Route connection direction enum."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


SPRITE_FACING = {
    "SPRITE_FACING_DOWN": Direction.SOUTH,
    "SPRITE_FACING_UP": Direction.NORTH,
    "SPRITE_FACING_LEFT": Direction.WEST,
    "SPRITE_FACING_RIGHT": Direction.EAST,
}

WATER_TILE = 0x14
SHORE_TILES = {0x32, 0x48}  # skipped when the tileset is SHIP_PORT


class NPCMovement(str, Enum):
    """NPC Movement enum."""

    STAY = "stay"
    WALK = "walk"


class Connection(BaseModel):
    """Route connection model."""

    direction: Direction
    target_const: str = Field(description="Map constant, for example ROUTE_1")
    target_label: str
    offset: int = Field(description="In blocks")


class Warp(BaseModel):
    """Warp macro model."""

    x: int = Field(description="In step coordinates (16x16 px sqaures)")
    y: int = Field(description="In step coordinates (16x16 px sqaures)")
    dest_map: str = Field(description="Map constant or LAST_MAP (0xFF)")
    dest_warp: int = Field(description="index into dest_map warps")


class ObjBase(BaseModel):
    """Common base class for map objects."""

    x: int
    y: int
    sprite: str
    movement: str
    facing: str
    text_id: str


# Optional: remove redunant NPC model in memory/models.py
class Npc(ObjBase):
    """Npc map object."""

    kind: Literal["npc"] = "npc"


class ItemBall(ObjBase):
    """ItemBall map object."""

    kind: Literal["item"] = "item"
    item: str


class Trainer(ObjBase):
    """Trainer map object."""

    kind: Literal["trainer"] = "trainer"
    trainer_class: str
    trainer_num: int


class StaticMon(ObjBase):
    """Static pokemon map object."""

    kind: Literal["static"] = "static"
    species: str
    level: int


MapObject = Annotated[
    Npc | ItemBall | Trainer | StaticMon,
    Field(discriminator="kind"),
]


class Sign(BaseModel):
    """Sign object model."""

    x: int
    y: int
    text_id: str


class GameMapConstant(BaseModel):
    """Game map constant model."""

    const: str = Field(description="Used as key to identiy map, e.g. ROUTE_1")
    idx: int
    width: int
    height: int


class Tileset(BaseModel):
    """Tileset model."""

    name: str
    blocks: bytes
    collision: set[int]
    water: set[int] = Field(default_factory=set)
    pair_collisions_land: set[frozenset[int]] = Field(default_factory=set)
    pair_collisions_water: set[frozenset[int]] = Field(default_factory=set)
    ledges: list[tuple[Direction, int, int]] = Field(default_factory=list)
    counter_tiles: set[int] = Field(default_factory=set)
    grass_tile: int | None = None

    @property
    def num_blocks(self) -> int:
        """Calculate the number of blocks in the tileset."""
        return len(self.blocks) // 16


class GameMap(GameMapConstant):
    """Game Map model."""

    label: str = Field(description="Tilecased const name")
    tileset: str
    blocks: bytes
    connections: list[Connection] = Field(default_factory=list)
    warps: list[Warp] = Field(default_factory=list)
    map_objects: list[MapObject] = Field(default_factory=list)
    signs: list[Sign] = Field(default_factory=list)

    @property
    def step_width(self) -> int:
        """Calculate step width from block width."""
        return self.width * 2

    @property
    def step_height(self) -> int:
        """Calculate step height from block height."""
        return self.height * 2
