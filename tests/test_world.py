"""Tests for the world model built from the pokered data."""

import pytest

from agent_oak.executor.graph import nearest_node
from agent_oak.executor.models import World
from agent_oak.parser.maps import parse_maps, parse_tilesets


@pytest.fixture(scope="module")
def world() -> World:
    """Build the world once, parsing every map takes a moment."""
    maps, _ = parse_maps()
    tilesets, _ = parse_tilesets()
    return World(maps=maps, tilesets=tilesets)


def test_doorway_groups_adjacent_warps_to_the_same_map(world: World) -> None:
    """Both halves of a gate exit belong to one doorway, the other exit not."""
    gate = "VIRIDIAN_FOREST_SOUTH_GATE"

    assert world.doorway((gate, 4, 0)) == [(gate, 4, 0), (gate, 5, 0)]
    assert world.doorway((gate, 5, 7)) == [(gate, 5, 7), (gate, 4, 7)]
    assert world.doorway((gate, 2, 2)) == [(gate, 2, 2)]


def test_warp_destinations(world: World) -> None:
    """The south gate's top exit leads into the forest."""
    dests = world.warp_destinations(("VIRIDIAN_FOREST_SOUTH_GATE", 4, 0))

    assert {d[0] for d in dests} == {"VIRIDIAN_FOREST"}


def test_nearest_node_enters_a_map_without_warps(world: World) -> None:
    """ROUTE_1 has no warps, coming from the north it is entered at the top."""
    entry = nearest_node(
        world=world,
        start=("PEWTER_GYM", 4, 13),
        is_goal=lambda n: n[0] == "ROUTE_1",
    )

    assert entry is not None
    assert entry[0] == "ROUTE_1"
    assert entry[2] == 0


def test_game_map_dump_leaves_out_blocks(world: World) -> None:
    """The raw block data is not part of tool output."""
    assert "blocks" not in world.maps["ROUTE_1"].model_dump()
