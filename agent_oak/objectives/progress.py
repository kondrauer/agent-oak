"""Progress signals across action calls, to notice when the player is stuck."""

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

HintMode = Literal["off", "on_request", "auto"]


@dataclass(frozen=True)
class HintPolicy:
    """How hints are given.

    off: only the goal's name, no hints or routing (honest benchmarking).
    on_request: hints and routing when the LLM asks for them.
    auto: also raise the hint tier when progress stalls, up to max_auto_tier.
    """

    mode: HintMode = "auto"
    max_auto_tier: int = 2
    stall_calls: int = 40
    """Action calls without a progress signal before the tier goes up."""
    oscillation_transitions: int = 10
    """Map changes between at most oscillation_maps maps that count as stuck."""
    oscillation_maps: int = 3


@dataclass(frozen=True)
class Position:
    """What the progress signals are computed from, read after an action."""

    map: str
    x: int
    y: int
    in_battle: bool
    party_levels: tuple[int, ...]
    badges: int


@dataclass
class Update:
    """The result of one action call."""

    signals: list[str]
    """Progress made, e.g. "new map", "level up". Empty when none."""
    stalled: bool = False
    """No progress for stall_calls calls."""
    oscillating: list[str] | None = None
    """The few maps the player keeps going between, if that is the case."""


@dataclass
class Progress:
    """Remember where the player has been and how long since progress."""

    policy: HintPolicy = field(default_factory=HintPolicy)
    visited: dict[str, set[tuple[int, int]]] = field(default_factory=dict)
    calls_since_progress: int = 0
    transitions: deque[str] = field(default_factory=deque)
    last: Position | None = None

    def update(self, pos: Position, completed: int = 0) -> Update:
        """Account for one action call that ended at 'pos'.

        Args:
            pos: Where the player is and the party / badge state.
            completed: Milestones completed by this call.
        Returns:
            The progress signals and whether the player looks stuck.
        """
        signals: list[str] = []
        if completed:
            signals.append("milestone")
        tiles = self.visited.setdefault(pos.map, set())
        if not tiles:
            signals.append("new map")
        if (pos.x, pos.y) not in tiles:
            tiles.add((pos.x, pos.y))
            signals.append("new tile")

        last = self.last
        oscillating = None
        if last is not None:
            if sum(pos.party_levels) > sum(last.party_levels):
                signals.append("level up")
            if pos.badges & ~last.badges:
                signals.append("badge")
            if pos.map != last.map:
                oscillating = self._transition(pos.map)
        self.last = pos

        stalled = False
        if signals:
            self.calls_since_progress = 0
        elif not pos.in_battle:
            # long battles are not being stuck
            self.calls_since_progress += 1
            if self.calls_since_progress >= self.policy.stall_calls:
                stalled = True
                self.calls_since_progress = 0
        return Update(signals=signals, stalled=stalled, oscillating=oscillating)

    def _transition(self, new_map: str) -> list[str] | None:
        """Record a map change, return the maps if it is back and forth."""
        window = self.policy.oscillation_transitions
        self.transitions.append(new_map)
        while len(self.transitions) > window:
            self.transitions.popleft()
        maps = list(dict.fromkeys(self.transitions))
        if (
            len(self.transitions) == window
            and len(maps) <= self.policy.oscillation_maps
        ):
            self.transitions.clear()
            return maps
        return None

    def to_json(self) -> dict[str, Any]:
        """Serializable state, positions packed as [x, y] lists."""
        return {
            "visited": {m: sorted(map(list, t)) for m, t in self.visited.items()},
            "calls_since_progress": self.calls_since_progress,
            "transitions": list(self.transitions),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], policy: HintPolicy) -> "Progress":
        """Restore what to_json saved."""
        return cls(
            policy=policy,
            visited={
                m: {(x, y) for x, y in tiles}
                for m, tiles in data.get("visited", {}).items()
            },
            calls_since_progress=data.get("calls_since_progress", 0),
            transitions=deque(data.get("transitions", [])),
        )
