"""Data models for Pokemon MCP memory parsing."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from agent_oak.memory.mappings import (
    BattleType,
    PokemonTypes,
    StatusFlags,
)
from agent_oak.parser.maps import GameMap
from agent_oak.parser.models import Direction, MapObject, Sign


class Button(str, Enum):
    """Button name enumeration."""

    A = "a"
    B = "b"
    START = "start"
    SELECT = "select"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class Menu(BaseModel):
    """A menu or prompt waiting for a choice."""

    kind: Literal["menu", "battle_menu", "move_menu", "party_menu"] = Field(
        description="battle_menu is the FIGHT / PKMN / ITEM / RUN menu, "
        "move_menu the move list in battle, party_menu the party list"
    )
    options: list[str]
    selected: int = Field(description="Index of the option under the cursor")


class TextState(BaseModel):
    """What the text box currently shows."""

    box_open: bool
    text: list[str] = Field(description="Lines currently in the text box")
    waiting_for_a: bool = Field(description="The continue arrow is shown")
    menu: Menu | None = None


class DialogueResult(BaseModel):
    """Outcome of advancing a dialogue."""

    status: Literal["done", "menu", "battle_menu", "timeout"] = Field(
        description="done: text box closed, menu/battle_menu: waiting for a "
        "choice, timeout: still running after the frame budget"
    )
    text: str = Field(description="Every line shown, in order")
    menu: Menu | None = None


class Item(BaseModel):
    """Data model for an item in the player's inventory."""

    id: int
    name: str
    quantity: int


class BagItems(BaseModel):
    """Data model for the player's inventory."""

    items: list[Item]
    count: int


class ObtainedBadge(BaseModel):
    """Data model for an obtained badge."""

    name: str
    leader: str
    city: str


class ObtainedBadges(BaseModel):
    """Data model for the player's obtained badges."""

    badges: list[ObtainedBadge]
    count: int
    raw_bits: int


class PokemonStats(BaseModel):
    """Pokemon stats data model."""

    attack: int
    defense: int
    speed: int
    special: int


class BattlePokemon(BaseModel):
    """Data model for a Pokemon in battle."""

    species_id: int
    species: str
    level: int
    hp: int
    max_hp: int
    status: StatusFlags = Field(..., use_enum_values=False)
    moves: list[str]
    pp: list[int]
    type1: PokemonTypes = Field(..., use_enum_values=False)
    type2: PokemonTypes = Field(..., use_enum_values=False)
    nickname: str | None = None

    @field_serializer("status")
    def serialize_status(self, value: StatusFlags) -> str:
        """Serialize the status enum using its member name."""
        return value.name

    @field_serializer("type1")
    def serialize_type1(self, value: PokemonTypes) -> str:
        """Serialize the type1 enum using its member name."""
        return value.name

    @field_serializer("type2")
    def serialize_type2(self, value: PokemonTypes) -> str:
        """Serialize the type2 enum using its member name."""
        return value.name


class BattleState(BaseModel):
    """Data model for the state of a battle."""

    in_battle: bool
    battle_type: BattleType | str = Field(..., use_enum_values=False)
    player_pokemon: BattlePokemon | None
    enemy_pokemon: BattlePokemon | None

    @field_serializer("battle_type")
    def serialize_battle_type(self, value: BattleType | str) -> str:
        """Serialize the battle type using its member name."""
        return value.name if isinstance(value, BattleType) else value


class BattleTurn(BaseModel):
    """Outcome of a battle action."""

    dialogue: DialogueResult = Field(
        description="Text of the turn and the next menu (battle_menu when it "
        "is the player's turn again, done when the battle is over)"
    )
    battle: BattleState


class Pokemon(BaseModel):
    """Pokemon data model."""

    species_id: int
    species: str
    nickname: str
    original_trainer: str
    original_trainer_id: int
    level: int
    hp: int
    max_hp: int
    status: StatusFlags = Field(..., use_enum_values=False)
    type1: PokemonTypes = Field(..., use_enum_values=False)
    type2: PokemonTypes = Field(..., use_enum_values=False)
    moves: list[str]
    pp: list[int]
    stats: PokemonStats
    experience: int

    @field_serializer("status")
    def serialize_status(self, value: StatusFlags) -> str:
        """Serialize the status enum using its member name."""
        return value.name

    @field_serializer("type1")
    def serialize_type1(self, value: PokemonTypes) -> str:
        """Serialize the type1 enum using its member name."""
        return value.name

    @field_serializer("type2")
    def serialize_type2(self, value: PokemonTypes) -> str:
        """Serialize the type2 enum using its member name."""
        return value.name


class PlayerLocation(BaseModel):
    """Player location data model."""

    map_id: int
    map: GameMap
    tileset_name: str
    tileset_id: int
    x: int
    y: int


class Warp(BaseModel):
    """Warp data model."""

    x: int
    y: int
    dest_warp: int
    dest_map: int


class Npc(BaseModel):
    """Npc data model."""

    slot: int
    y: int
    x: int
    facing: int


class NpcInfo(BaseModel):
    """Live NPC position joined with its static map object."""

    slot: int
    x: int
    y: int
    facing: Direction | None
    object: MapObject | None = Field(
        default=None,
        description="Static data from the map header (sprite, text, trainer, item)",
    )


class MapObjects(BaseModel):
    """Things on the current map the player can talk to."""

    map: str
    npcs: list[NpcInfo]
    signs: list[Sign]
