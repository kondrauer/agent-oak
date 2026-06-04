"""Data models for Pokemon MCP memory parsing."""

from pydantic import BaseModel

from agent_oak.pokemon_mcp.mappings import BattleType, PokemonSpecies, StatusFlags


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
    species: PokemonSpecies
    level: int
    hp: int
    max_hp: int
    status: StatusFlags
    moves: list[int]
    pp: list[int]
    nickname: str | None = None


class BattleState(BaseModel):
    """Data model for the state of a battle."""

    in_battle: bool
    battle_type: BattleType | str
    player_pokemon: BattlePokemon | None
    enemy_pokemon: BattlePokemon | None


class Pokemon(BaseModel):
    """Pokemon data model."""

    species_id: int
    species: PokemonSpecies
    nickname: str
    original_trainer: str
    original_trainer_id: int
    level: int
    hp: int
    max_hp: int
    status: StatusFlags
    type1: int
    type2: int
    moves: list[int]
    pp: list[int]
    stats: PokemonStats
    experience: int


class PlayerLocation(BaseModel):
    """Player location data model."""

    map_id: int
    map_name: str
    tileset: str
    x: int
    y: int
