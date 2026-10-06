"""Tests for loading and validating data/objectives.yaml."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_oak.objectives.milestones import (
    OBJECTIVES_PATH,
    ObjectivesError,
    load_objectives,
    parse_objectives,
)
from agent_oak.parser.models import GameMap


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """Load the YAML of the real objectives."""
    return yaml.safe_load(Path(OBJECTIVES_PATH).read_text())


def _problems(
    doc: Any, constants: dict[str, Any], maps: dict[str, GameMap]
) -> list[str]:
    with pytest.raises(ObjectivesError) as err:
        parse_objectives(data=doc, constants=constants, maps=maps)
    return err.value.problems


def _milestone(doc: dict[str, Any], mid: str) -> dict[str, Any]:
    return next(m for m in doc["milestones"] if m["id"] == mid)


def test_objectives_load(maps: dict[str, GameMap]) -> None:
    """The shipped YAML validates, targets resolve to the map objects."""
    objectives = load_objectives(maps=maps)
    by_id = objectives.by_id()

    assert objectives.milestones[0].id == "MEET_OAK"
    assert by_id["BEAT_LT_SURGE"].requires == ("OPEN_SURGE_LOCKS",)
    captain = by_id["GET_HM01"].target
    assert captain is not None
    assert (captain.name, captain.x, captain.y) == ("SSANNECAPTAINSROOM_CAPTAIN", 4, 2)
    assert set(objectives.capabilities) >= {"CUT", "SURF", "STRENGTH", "FLASH"}


def test_misspelled_flag_fails(document, constants, maps) -> None:
    """A typo in an event name is caught at load time."""
    doc = deepcopy(document)
    _milestone(doc, "BEAT_MISTY")["done"] = {"event": "EVENT_BEAT_MISTI"}

    problems = _problems(doc, constants, maps)

    assert problems == ["BEAT_MISTY.done.event: unknown event 'EVENT_BEAT_MISTI'"]


def test_unknown_requires_and_cycles_fail(document, constants, maps) -> None:
    """Requires must name milestones and must not loop."""
    doc = deepcopy(document)
    _milestone(doc, "MEET_OAK")["requires"] = ["BEAT_BROCK"]
    _milestone(doc, "BEAT_MISTY")["requires"] = ["REACH_CERULEN"]

    problems = _problems(doc, constants, maps)

    assert "BEAT_MISTY.requires: unknown milestone 'REACH_CERULEN'" in problems
    assert any(p.startswith("requires form a cycle: MEET_OAK -> ") for p in problems)


def test_unresolvable_target_fails(document, constants, maps) -> None:
    """An npc target must be exactly one object on the milestone's map."""
    doc = deepcopy(document)
    _milestone(doc, "BEAT_MISTY")["target"] = {"npc": "BROCK"}
    _milestone(doc, "BEAT_BROCK")["map"] = "PEWTER_GYMM"

    problems = _problems(doc, constants, maps)

    expected = "BEAT_MISTY.target: npc 'BROCK' matches 0"
    assert any(p.startswith(expected) for p in problems)
    assert "BEAT_BROCK.map: unknown map 'PEWTER_GYMM'" in problems
