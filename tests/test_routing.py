"""Capability and blocker aware routing to milestone targets."""

from typing import Any

import pytest
from conftest import MakeRam

from agent_oak.executor.models import Node, World
from agent_oak.objectives.hints import hint_text
from agent_oak.objectives.milestones import Objectives, load_objectives
from agent_oak.objectives.ram import Ram
from agent_oak.objectives.routing import (
    Route,
    install_blockers,
    plan_route,
    route_context,
)
from agent_oak.parser.maps import parse_tilesets
from agent_oak.parser.models import GameMap


@pytest.fixture(scope="module")
def world(maps: dict[str, GameMap]) -> World:
    """Build the world of the parsed maps, with the openable blocker tiles."""
    world = World(maps=maps, tilesets=parse_tilesets()[0])
    install_blockers(world=world, objectives=load_objectives(maps=maps))
    return world


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
        badges: tuple[str, ...] = (),
    ) -> Ram:
        hidden = tuple(t for t in initially_hidden if t not in show) + hide
        return make_ram(events=events, hidden=hidden, bag=bag, badges=badges)

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


def test_rock_tunnel_needs_cut(world, objectives, maps, ram) -> None:
    """With the Saffron gates closed Lavender is behind Route 9's tree."""
    args = (world, objectives, maps, "REACH_LAVENDER", "VERMILION_CITY")
    after_ticket = ram(
        hide=("TOGGLE_CERULEAN_GUARD_2",), show=("TOGGLE_CERULEAN_GUARD_1",)
    )

    assert _route(*args, after_ticket).blocked_by == ["CUT"]
    route = _route(*args, after_ticket, ("CUT",))
    assert "ROCK_TUNNEL_1F" in route.maps and "SAFFRON_CITY" not in route.maps


def test_saffron_gates_open_with_a_drink(world, objectives, maps, ram) -> None:
    """A drink in the bag opens the gates, then Celadon is through Saffron."""
    args = (world, objectives, maps, "REACH_CELADON", "VERMILION_CITY")

    closed = _route(*args, ram(), ("CUT",))
    open_ = _route(*args, ram(bag={"FRESH_WATER": 1}), ("CUT",))

    assert "SAFFRON_CITY" not in closed.maps
    assert "SAFFRON_CITY" in open_.maps and open_.steps < closed.steps


def test_rocket_hideout(world, objectives, maps, ram) -> None:
    """Giovanni is behind the poster, the lift and the B4F door."""
    args = (world, objectives, maps, "BEAT_HIDEOUT_GIOVANNI", "CELADON_CITY")
    found = ("EVENT_FOUND_ROCKET_HIDEOUT",)
    beaten = ("TOGGLE_GAME_CORNER_ROCKET",)
    door = found + ("EVENT_ROCKET_HIDEOUT_4_DOOR_UNLOCKED",)

    assert set(_route(*args, ram()).blocked_by) >= {"GAME_CORNER_STAIRS"}
    assert _route(*args, ram(events=door, hide=beaten)).blocked_by == [
        "ROCKET_HIDEOUT_LIFT"
    ]
    with_key = ram(events=found, hide=beaten, bag={"LIFT_KEY": 1})
    assert _route(*args, with_key).blocked_by == ["ROCKET_HIDEOUT_B4F_DOOR"]
    route = _route(*args, ram(events=door, hide=beaten, bag={"LIFT_KEY": 1}))
    assert route.status == "route" and "ROCKET_HIDEOUT_ELEVATOR" in route.maps


def test_pokemon_tower(world, objectives, maps, ram) -> None:
    """The ghost is the goal itself first, then blocks the way to Mr. Fuji."""
    ghost = _route(
        world, objectives, maps, "BEAT_MAROWAK_GHOST", "LAVENDER_TOWN", ram()
    )
    fuji = _route(world, objectives, maps, "RESCUE_MR_FUJI", "LAVENDER_TOWN", ram())

    assert ghost.status == "route"
    assert fuji.blocked_by == ["POKEMON_TOWER_GHOST"]


def test_snorlax_blocks_the_way_to_fuchsia(world, objectives, maps, ram) -> None:
    """Fuchsia is behind a Snorlax until the Poke Flute woke one."""
    args = (world, objectives, maps, "REACH_FUCHSIA", "LAVENDER_TOWN")

    assert _route(*args, ram(), ("CUT",)).blocked_by == ["ROUTE_12_SNORLAX"]
    awake = ram(hide=("TOGGLE_ROUTE_12_SNORLAX",))
    assert _route(*args, awake, ("CUT",)).status == "route"


def test_silph_co(world, objectives, maps, ram) -> None:
    """Silph Co opens after Mr. Fuji, Giovanni is behind card key doors."""
    drink = {"FRESH_WATER": 1}
    fuji = ("TOGGLE_SAFFRON_CITY_E",)
    args = (world, objectives, maps, "BEAT_SILPH_GIOVANNI", "SAFFRON_CITY")

    assert "SILPH_CO_ENTRANCE" in _route(*args, ram(bag=drink)).blocked_by
    no_key = _route(*args, ram(hide=fuji, bag=drink)).blocked_by
    assert no_key and all(b.startswith("SILPH_CO_") for b in no_key)
    key = _route(*args, ram(hide=fuji, bag=drink | {"CARD_KEY": 1}))
    assert key.status == "route"


def test_sabrina_after_silph_co(world, objectives, maps, ram) -> None:
    """A grunt blocks Saffron Gym until Giovanni left Silph Co."""
    args = (world, objectives, maps, "BEAT_SABRINA", "SAFFRON_CITY")
    rockets = tuple(f"TOGGLE_SAFFRON_CITY_{i}" for i in "1234567")

    assert _route(*args, ram()).blocked_by == ["SAFFRON_GYM_ROCKET"]
    assert _route(*args, ram(hide=rockets)).status == "route"


SEVEN_BADGES = ("BOULDER", "CASCADE", "THUNDER", "RAINBOW", "SOUL", "MARSH", "VOLCANO")
FIELD_MOVES = ("CUT", "SURF", "STRENGTH")


def test_gyms_of_segment_4(world, objectives, maps, ram) -> None:
    """Cinnabar Gym needs the Secret Key, Viridian Gym seven badges."""
    blaine = (world, objectives, maps, "BEAT_BLAINE", "CINNABAR_ISLAND")
    giovanni = (world, objectives, maps, "BEAT_GIOVANNI", "VIRIDIAN_CITY")

    assert _route(*blaine, ram()).blocked_by == ["CINNABAR_GYM_DOOR"]
    assert _route(*blaine, ram(bag={"SECRET_KEY": 1})).status == "route"
    dex = {"events": ("EVENT_GOT_POKEDEX",), "hide": ("TOGGLE_LYING_OLD_MAN",)}
    six = ram(badges=SEVEN_BADGES[:6], **dex)
    assert _route(*giovanni, six).blocked_by == ["VIRIDIAN_GYM_DOOR"]
    assert _route(*giovanni, ram(badges=SEVEN_BADGES, **dex)).status == "route"


def test_route_23_wants_every_badge(world, objectives, maps, ram) -> None:
    """The guard nearest Victory Road checks the Earth Badge."""
    args = (world, objectives, maps, "REACH_INDIGO_PLATEAU", "VIRIDIAN_CITY")

    seven = _route(*args, ram(badges=SEVEN_BADGES), FIELD_MOVES)
    eight = _route(*args, ram(badges=SEVEN_BADGES + ("EARTH",)), FIELD_MOVES)

    assert seven.blocked_by == ["ROUTE_23_EARTH_GUARD"]
    assert eight.status == "route" and "VICTORY_ROAD_1F" in eight.maps


def test_elite_four_doors(world, objectives, maps, ram) -> None:
    """Each room's exit opens with its trainer, Lorelei's from closed data."""
    lobby = maps["INDIGO_PLATEAU_LOBBY"]
    start = ("INDIGO_PLATEAU_LOBBY", lobby.warps[0].x + 1, lobby.warps[0].y - 1)
    champion = objectives.by_id()["BEAT_CHAMPION"]
    beaten = (
        "EVENT_BEAT_LORELEIS_ROOM_TRAINER_0",
        "EVENT_BEAT_BRUNOS_ROOM_TRAINER_0",
        "EVENT_BEAT_AGATHAS_ROOM_TRAINER_0",
    )

    def route(events: tuple[str, ...]) -> Route:
        return plan_route(
            world=world,
            milestone=champion,
            start=start,
            context=route_context(
                objectives=objectives, maps=maps, ram=ram(events=events)
            ),
        )

    assert route(()).blocked_by == ["AGATHA_EXIT", "BRUNO_EXIT", "LORELEI_EXIT"]
    assert route(beaten[:1]).blocked_by == ["AGATHA_EXIT", "BRUNO_EXIT"]
    assert route(beaten).status == "route"
