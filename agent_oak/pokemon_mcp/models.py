"""Data models for Pokemon MCP memory parsing."""

from pydantic import BaseModel, Field, field_serializer

from agent_oak.pokemon_mcp.mappings import (
    BattleType,
    PokemonTypes,
    StatusFlags,
)


class Dialogue(BaseModel):
    """Data model for dialogue text."""

    text: str
    has_dialogue: bool


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
    map_name: str
    tileset: str
    x: int
    y: int
