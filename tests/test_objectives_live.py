"""Objective checks against the real save after Brock."""

from typing import Any

from agent_oak.objectives.ram import Ram


def test_event_bits_match_the_save(
    constants: dict[str, Any], ram_after_brock: Ram
) -> None:
    """Brock is beaten, Misty not: the event bit math is right."""
    events = constants["events"]

    assert ram_after_brock.bit("wEventFlags", events["EVENT_BEAT_BROCK"])
    assert ram_after_brock.bit("wEventFlags", events["EVENT_GOT_TM34"])
    assert not ram_after_brock.bit("wEventFlags", events["EVENT_BEAT_MISTY"])
    assert ram_after_brock.data["wObtainedBadges"] == b"\x01"
