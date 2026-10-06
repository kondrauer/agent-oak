"""Tests for the progress signals and stuck detection."""

from agent_oak.objectives.progress import HintPolicy, Position, Progress


def _pos(
    map_: str = "ROUTE_3",
    x: int = 1,
    y: int = 1,
    in_battle: bool = False,
    levels: tuple[int, ...] = (15,),
    badges: int = 1,
) -> Position:
    return Position(
        map=map_, x=x, y=y, in_battle=in_battle, party_levels=levels, badges=badges
    )


def test_signals() -> None:
    """New maps and tiles, level ups, badges and milestones are progress."""
    progress = Progress()

    assert progress.update(_pos()).signals == ["new map", "new tile"]
    assert progress.update(_pos()).signals == []
    assert progress.update(_pos(x=2)).signals == ["new tile"]
    assert progress.update(_pos(x=2, levels=(16,))).signals == ["level up"]
    assert progress.update(_pos(x=2, levels=(16,), badges=3)).signals == ["badge"]
    assert progress.update(_pos(x=2, levels=(16,), badges=3), completed=1).signals == [
        "milestone"
    ]


def test_stall_after_n_calls_without_progress() -> None:
    """The Nth call without progress stalls, then counting starts over."""
    progress = Progress(policy=HintPolicy(stall_calls=3))
    progress.update(_pos())

    assert [progress.update(_pos()).stalled for _ in range(7)] == [
        False,
        False,
        True,
        False,
        False,
        True,
        False,
    ]


def test_progress_and_battles_reset_or_pause_the_count() -> None:
    """Progress resets the stall count, calls in battle do not count."""
    progress = Progress(policy=HintPolicy(stall_calls=3))
    progress.update(_pos())
    progress.update(_pos())
    progress.update(_pos())
    progress.update(_pos(x=5))  # new tile

    assert not progress.update(_pos(x=5)).stalled
    assert not progress.update(_pos(x=5)).stalled
    for _ in range(10):
        assert not progress.update(_pos(x=5, in_battle=True)).stalled
    assert progress.update(_pos(x=5)).stalled


def test_oscillation_between_few_maps() -> None:
    """Going back and forth between two maps is flagged, once per window."""
    progress = Progress(policy=HintPolicy(oscillation_transitions=4))
    flagged = []
    for i in range(9):
        update = progress.update(_pos("PEWTER_CITY" if i % 2 else "ROUTE_3"))
        flagged.append(update.oscillating)

    assert flagged[:4] == [None] * 4
    assert flagged[4] == ["PEWTER_CITY", "ROUTE_3"]
    assert flagged[5:8] == [None] * 3
    assert flagged[8] == ["PEWTER_CITY", "ROUTE_3"]


def test_new_maps_are_not_oscillation() -> None:
    """Walking through many maps in a row is just travelling."""
    progress = Progress(policy=HintPolicy(oscillation_transitions=4))
    maps = ["A", "B", "C", "D", "E", "F", "G"]

    assert all(progress.update(_pos(m)).oscillating is None for m in maps)


def test_json_round_trip() -> None:
    """Visited tiles, stall count and transitions survive a restart."""
    policy = HintPolicy(stall_calls=3)
    progress = Progress(policy=policy)
    progress.update(_pos())
    progress.update(_pos("PEWTER_CITY", x=4))
    progress.update(_pos("PEWTER_CITY", x=4))

    restored = Progress.from_json(progress.to_json(), policy)

    assert restored.visited == {"ROUTE_3": {(1, 1)}, "PEWTER_CITY": {(4, 1)}}
    assert restored.calls_since_progress == 1
    assert list(restored.transitions) == ["PEWTER_CITY"]
