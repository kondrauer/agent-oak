"""Capability and blocker aware routing to milestone targets."""

from typing import Any

import pytest
from conftest import MakeRam

from agent_oak.executor.models import Node, World
from agent_oak.objectives.hints import hint_text
from agent_oak.objectives.milestones import Objectives, load_objectives
from agent_oak.objectives.ram import Ram
from agent_oak.objectives.routing import Route, plan_route, route_context
from agent_oak.parser.maps import parse_tilesets
from agent_oak.parser.models import GameMap


@pytest.fixture(scope="module")
def world(maps: dict[str, GameMap]) -> World:
    """Build the world of the parsed maps."""
    return World(maps=maps, tilesets=parse_tilesets()[0])


@pytest.fixture(scope="module")
def objectives(maps: dict[str, GameMap]) -> Objectives:
    """Load the shipped milestones and blockers."""
    return load_objectives(maps=maps)


@pytest.fixture
def ram(constants: dict[str, Any], make_ram: MakeRam):
    """Build RAM like the game sets it up: objects hidden at the start are hidden."""
    initially_hidden = tuple(
        name for name, t in constants["toggles"].items() if not t["initially_shown"]
    )

    def ram(
        events: tuple[str, ...] = (),
        hide: tuple[str, ...] = (),
        show: tuple[str, ...] = (),
        bag: dict[str, int] | None = None,
    ) -> Ram:
        hidden = tuple(t for t in initially_hidden if t not in show) + hide
        return make_ram(events=events, hidden=hidden, bag=bag)

    return ram


def _front_of_pokecenter(maps: dict[str, GameMap], city: str) -> Node:
    """Find the tile below a city's Pokecenter door, a safe place to start."""
    door = next(w for w in maps[city].warps if w.dest_map.endswith("POKECENTER"))
    return (city, door.x, door.y + 1)


def _route(world, objectives, maps, milestone: str, city: str, ram, caps=()) -> Route:
    return plan_route(
        world=world,
        milestone=objectives.by_id()[milestone],
        start=_front_of_pokecenter(maps, city),
        abilities=caps,
        context=route_context(objectives=objectives, maps=maps, ram=ram),
    )


def test_vermilion_gym_needs_cut(world, objectives, maps, ram) -> None:
    """The plan's done check: in Vermilion without Cut the gym is behind CUT."""
    without = _route(
        world, objectives, maps, "OPEN_SURGE_LOCKS", "VERMILION_CITY", ram()
    )
    with_cut = _route(
        world, objectives, maps, "OPEN_SURGE_LOCKS", "VERMILION_CITY", ram(), ("CUT",)
    )

    assert without.status == "blocked"
    assert without.blocked_by == ["CUT"]
    assert without.blocked_reasons[0].startswith("CUT: a small tree")
    assert with_cut.status == "route" and with_cut.blocked_by == []


def test_surge_behind_the_electric_door(world, objectives, maps, ram) -> None:
    """With Cut the gym is open, Surge waits behind the locked door."""
    args = (world, objectives, maps, "BEAT_LT_SURGE", "VERMILION_CITY")
    locked = _route(*args, ram(), ("CUT",))
    opened = _route(*args, ram(events=("EVENT_2ND_LOCK_OPENED",)), ("CUT",))

    assert locked.blocked_by == ["VERMILION_GYM_DOOR"]
    assert opened.status == "route"


def test_ss_anne_needs_the_ticket(world, objectives, maps, ram) -> None:
    """The dock sailor lets the player through with the ticket only."""
    args = (world, objectives, maps, "GET_HM01", "VERMILION_CITY")

    assert _route(*args, ram()).blocked_by == ["VERMILION_DOCK_SAILOR"]
    assert _route(*args, ram(bag={"S_S_TICKET": 1})).status == "route"
    left = ram(events=("EVENT_SS_ANNE_LEFT",), bag={"S_S_TICKET": 1})
    assert _route(*args, left).blocked_by == ["VERMILION_DOCK_SAILOR"]


def test_viridian_old_man(world, objectives, maps, ram) -> None:
    """North of Viridian is closed until the Pokedex, he moves then."""
    args = (world, objectives, maps, "REACH_PEWTER", "VIRIDIAN_CITY")
    after = ram(
        events=("EVENT_GOT_POKEDEX",),
        hide=("TOGGLE_LYING_OLD_MAN",),
        show=("TOGGLE_OLD_MAN",),
    )

    assert _route(*args, ram()).blocked_by == ["VIRIDIAN_OLD_MAN"]
    assert _route(*args, after).status == "route"


def test_cerulean_south_through_the_robbed_house(world, objectives, maps, ram) -> None:
    """Route 5 is behind the guard until Bill's ticket moves him."""
    args = (world, objectives, maps, "REACH_VERMILION", "CERULEAN_CITY")
    after_ticket = ram(
        hide=("TOGGLE_CERULEAN_GUARD_2",), show=("TOGGLE_CERULEAN_GUARD_1",)
    )

    before = _route(*args, ram())
    after = _route(*args, after_ticket)

    assert before.blocked_by == ["CERULEAN_GUARD"]
    assert after.status == "route"
    assert after.maps[:3] == [
        "CERULEAN_CITY",
        "CERULEAN_TRASHED_HOUSE",
        "CERULEAN_CITY",
    ]


def test_pewter_east_exit(world, objectives, maps, ram) -> None:
    """Route 3 is closed until Brock is beaten."""
    args = (world, objectives, maps, "BEAT_MT_MOON_SUPER_NERD", "PEWTER_CITY")

    assert _route(*args, ram()).blocked_by == ["PEWTER_EAST_EXIT"]
    assert _route(*args, ram(events=("EVENT_BEAT_BROCK",))).status == "route"


def test_hint_names_the_blocker(world, objectives, maps, ram) -> None:
    """From tier 2 on the hint says what is in the way."""
    route = _route(world, objectives, maps, "OPEN_SURGE_LOCKS", "VERMILION_CITY", ram())
    milestone = objectives.by_id()["OPEN_SURGE_LOCKS"]

    tier2 = hint_text(milestone, tier=2, route=route)
    tier3 = hint_text(milestone, tier=3, route=route)

    assert "The way there is blocked by CUT: a small tree, you need Cut" in tier2
    assert "Path: blocked by CUT, " in tier3
