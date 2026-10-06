"""Tests for the objective predicates on synthetic RAM."""

from typing import Any

import pytest
from conftest import MakeRam

from agent_oak.objectives.predicates import Predicate, PredicateParser


@pytest.fixture
def parse(constants: dict[str, Any]):
    """Parse a predicate and fail the test on any error."""

    def parse(spec: Any, capabilities: dict[str, Predicate] | None = None) -> Predicate:
        parser = PredicateParser(constants=constants, capabilities=capabilities)
        predicate = parser.parse(spec, "test")
        assert parser.errors == []
        return predicate

    return parse


def test_event_flag(parse, make_ram: MakeRam) -> None:
    """An event predicate tests its own bit only."""
    p = parse({"event": "EVENT_BEAT_BROCK"})

    assert p.evaluate(make_ram(events=("EVENT_BEAT_BROCK",)))
    assert not p.evaluate(make_ram(events=("EVENT_GOT_TM34", "EVENT_BEAT_MISTY")))


def test_badge(parse, make_ram: MakeRam) -> None:
    """Badges are bits 0 (Boulder) to 7 (Earth) of wObtainedBadges."""
    p = parse({"badge": "CASCADE"})

    assert p.evaluate(make_ram(badges=("CASCADE",)))
    assert not p.evaluate(make_ram(badges=("BOULDER", "THUNDER")))
    assert make_ram(badges=("CASCADE",)).data["wObtainedBadges"] == b"\x02"


def test_items_in_bag_and_pc(parse, make_ram: MakeRam) -> None:
    """Item looks in the bag only, item_anywhere also in the PC."""
    bag = parse({"item": "S_S_TICKET"})
    anywhere = parse({"item_anywhere": "S_S_TICKET"})
    in_pc = make_ram(bag={"POTION": 3}, box={"S_S_TICKET": 1})

    assert bag.evaluate(make_ram(bag={"POTION": 3, "S_S_TICKET": 1}))
    assert not bag.evaluate(in_pc)
    assert anywhere.evaluate(in_pc)
    assert not anywhere.evaluate(make_ram(bag={"POTION": 3}))


def test_town_visited(parse, make_ram: MakeRam) -> None:
    """Towns are bits of the two wTownVisitedFlag bytes by map id."""
    p = parse({"visited": "SAFFRON_CITY"})  # map id $0A, second byte

    assert p.evaluate(make_ram(towns=("SAFFRON_CITY",)))
    assert not p.evaluate(make_ram(towns=("CERULEAN_CITY",)))


def test_object_hidden(parse, make_ram: MakeRam) -> None:
    """A set bit in wToggleableObjectFlags hides the object."""
    p = parse({"object_hidden": "TOGGLE_NUGGET_BRIDGE_GUY"})

    assert p.evaluate(make_ram(hidden=("TOGGLE_NUGGET_BRIDGE_GUY",)))
    assert not p.evaluate(make_ram())


def test_party_move_and_capability(parse, make_ram: MakeRam) -> None:
    """CUT needs the Cascade Badge and a party Pokemon that knows it."""
    cut = parse({"all": [{"badge": "CASCADE"}, {"party_move": "CUT"}]})
    p = parse({"capability": "CUT"}, capabilities={"CUT": cut})
    knows_cut = [(15, ["TACKLE"]), (12, ["SCRATCH", "CUT"])]

    assert p.evaluate(make_ram(badges=("CASCADE",), party=knows_cut))
    assert not p.evaluate(make_ram(party=knows_cut))
    assert not p.evaluate(make_ram(badges=("CASCADE",), party=[(15, ["TACKLE"])]))
    assert p.describe() == "can use CUT"


def test_combinators(parse, make_ram: MakeRam) -> None:
    """any, all and not combine predicates."""
    p = parse(
        {
            "any": [
                {"event": "EVENT_GOT_HM01"},
                {"not": {"object_hidden": "TOGGLE_CERULEAN_GUARD_2"}},
            ]
        }
    )

    assert p.evaluate(make_ram())
    assert not p.evaluate(make_ram(hidden=("TOGGLE_CERULEAN_GUARD_2",)))
    assert p.evaluate(
        make_ram(events=("EVENT_GOT_HM01",), hidden=("TOGGLE_CERULEAN_GUARD_2",))
    )


def test_unknown_names_are_errors(constants: dict[str, Any]) -> None:
    """Every unknown name and predicate kind is reported, not just the first."""
    parser = PredicateParser(constants=constants)
    parser.parse(
        {
            "all": [
                {"event": "EVENT_BEAT_MISTI"},
                {"badge": "CASCADE"},
                {"item": "SS_TICKET"},
                {"flag": "X"},
            ]
        },
        "test",
    )

    assert len(parser.errors) == 3
    assert "EVENT_BEAT_MISTI" in parser.errors[0]
    assert "SS_TICKET" in parser.errors[1]
    assert "unknown predicate 'flag'" in parser.errors[2]
