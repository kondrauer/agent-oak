"""Tests for evaluating milestones and computing the frontier."""

from typing import Any

import pytest
from conftest import MakeRam

from agent_oak.objectives.evaluator import Evaluator, primary
from agent_oak.objectives.milestones import load_objectives, parse_objectives
from agent_oak.objectives.ram import Ram
from agent_oak.parser.models import GameMap

# A -> B -> D, A -> C -> D, E is a side quest open from the start
GRAPH = {
    "milestones": [
        {
            "id": "A",
            "label": "A",
            "done": {"event": "EVENT_GOT_STARTER"},
            "blurb": "a",
            "tags": ["main"],
        },
        {
            "id": "E",
            "label": "E",
            "done": {"event": "EVENT_GOT_TOWN_MAP"},
            "blurb": "e",
        },
        {
            "id": "B",
            "label": "B",
            "done": {"badge": "BOULDER"},
            "requires": ["A"],
            "blurb": "b",
            "tags": ["main"],
        },
        {
            "id": "C",
            "label": "C",
            "done": {"visited": "CERULEAN_CITY"},
            "requires": ["A"],
            "blurb": "c",
            "tags": ["main"],
        },
        {
            "id": "D",
            "label": "D",
            "done": {"badge": "CASCADE"},
            "requires": ["B", "C"],
            "blurb": "d",
            "tags": ["main"],
        },
    ]
}


@pytest.fixture(scope="module")
def evaluator(constants: dict[str, Any], maps: dict[str, GameMap]) -> Evaluator:
    """Evaluate the synthetic graph."""
    objectives = parse_objectives(data=GRAPH, constants=constants, maps=maps)
    return Evaluator(objectives=objectives, num_events=constants["num_events"])


def _frontier(evaluator: Evaluator, ram: Ram) -> list[str]:
    return [m.id for m in evaluator.frontier(evaluator.evaluate(ram))]


def test_frontier_new_game(evaluator: Evaluator, make_ram: MakeRam) -> None:
    """Only milestones without prerequisites are open, main ones first."""
    assert _frontier(evaluator, make_ram()) == ["A", "E"]


def test_frontier_branches(evaluator: Evaluator, make_ram: MakeRam) -> None:
    """Both branches open after A, D waits for both of them."""
    ram = make_ram(events=("EVENT_GOT_STARTER",))
    assert _frontier(evaluator, ram) == ["B", "C", "E"]

    ram = make_ram(events=("EVENT_GOT_STARTER",), badges=("BOULDER",))
    assert _frontier(evaluator, ram) == ["C", "E"]

    ram = make_ram(
        events=("EVENT_GOT_STARTER",), badges=("BOULDER",), towns=("CERULEAN_CITY",)
    )
    frontier = evaluator.frontier(evaluator.evaluate(ram))
    assert [m.id for m in frontier] == ["D", "E"]
    first = primary(frontier)
    assert first is not None and first.id == "D"


def test_sequence_break_counts_as_done(evaluator: Evaluator, make_ram: MakeRam) -> None:
    """A milestone done in RAM is done even if its prerequisites are not."""
    ram = make_ram(events=("EVENT_GOT_STARTER",), badges=("CASCADE",))
    state = evaluator.evaluate(ram)

    assert state["D"]
    assert _frontier(evaluator, ram) == ["B", "C", "E"]


def test_everything_done(evaluator: Evaluator, make_ram: MakeRam) -> None:
    """No frontier and no primary goal once all is done."""
    ram = make_ram(
        events=("EVENT_GOT_STARTER", "EVENT_GOT_TOWN_MAP"),
        badges=("BOULDER", "CASCADE"),
        towns=("CERULEAN_CITY",),
    )
    assert evaluator.frontier(evaluator.evaluate(ram)) == []
    assert primary([]) is None


def test_evaluate_is_cached(evaluator: Evaluator, make_ram: MakeRam) -> None:
    """Equal snapshots reuse the result, changed bytes do not."""
    first = evaluator.evaluate(make_ram(events=("EVENT_GOT_STARTER",)))
    first["A"] = False  # callers get a copy
    again = evaluator.evaluate(make_ram(events=("EVENT_GOT_STARTER",)))
    other = evaluator.evaluate(make_ram())

    assert again["A"]
    assert not other["A"]


def test_primary_after_brock(
    constants: dict[str, Any], maps: dict[str, GameMap], ram_after_brock: Ram
) -> None:
    """On the save after Brock the goal is the first milestone past him."""
    evaluator = Evaluator(
        objectives=load_objectives(maps=maps), num_events=constants["num_events"]
    )
    state = evaluator.evaluate(ram_after_brock)
    frontier = evaluator.frontier(state)

    assert state["BEAT_BROCK"]
    assert not state["BEAT_MT_MOON_SUPER_NERD"]
    assert [m.id for m in frontier] == ["BEAT_MT_MOON_SUPER_NERD"]
    assert evaluator.capabilities(ram_after_brock) == set()


def test_story_plays_through(constants: dict[str, Any], maps: dict[str, GameMap]):
    """Doing the primary goal over and over reaches every milestone in order."""
    objectives = load_objectives(maps=maps)
    evaluator = Evaluator(objectives=objectives, num_events=constants["num_events"])
    state = {m.id: False for m in objectives.milestones}
    order = []
    while (goal := primary(evaluator.frontier(state))) is not None:
        state[goal.id] = True
        order.append(goal.id)

    assert len(order) == len(objectives.milestones)
    assert order[:3] == ["MEET_OAK", "GET_STARTER", "BATTLE_RIVAL_LAB"]
    assert order[-1] == "BEAT_CHAMPION"
    gyms = ["BEAT_BROCK", "BEAT_MISTY", "BEAT_LT_SURGE", "BEAT_ERIKA"]
    gyms += ["BEAT_KOGA", "BEAT_SABRINA", "BEAT_BLAINE", "BEAT_GIOVANNI"]
    assert sorted(gyms, key=order.index) == gyms
