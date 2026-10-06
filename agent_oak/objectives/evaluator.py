"""Evaluate the milestones against RAM and find what to do next."""

from threading import Lock

from pyboy import PyBoy

from agent_oak.objectives.milestones import Milestone, Objectives
from agent_oak.objectives.ram import Ram

MAIN_TAG = "main"

State = dict[str, bool]


class Evaluator:
    """Check every milestone against a RAM snapshot.

    RAM is the truth: a milestone is done when its predicate holds, even if
    its prerequisites are not (sequence breaks). Results are cached by the
    snapshot's bytes, so calling it after every tool is cheap.
    """

    def __init__(self, objectives: Objectives, num_events: int) -> None:
        """Evaluate 'objectives'.

        Args:
            objectives: The loaded milestones and capabilities.
            num_events: Number of event flags, sizes the RAM snapshot.
        """
        self.objectives = objectives
        self.num_events = num_events
        self._cache: tuple[bytes, State] | None = None

    def snapshot(self, pyboy: PyBoy, syms: dict[str, int], mem_lock: Lock) -> Ram:
        """Read the RAM regions the predicates need, under mem_lock."""
        with mem_lock:
            return Ram.read(pyboy=pyboy, syms=syms, num_events=self.num_events)

    def evaluate(self, ram: Ram) -> State:
        """Whether each milestone is done, keyed by id in YAML order."""
        key = ram.key()
        if self._cache is not None and self._cache[0] == key:
            return dict(self._cache[1])
        state = {m.id: m.done.evaluate(ram) for m in self.objectives.milestones}
        self._cache = (key, state)
        return dict(state)

    def frontier(self, state: State) -> list[Milestone]:
        """Milestones that are not done but whose prerequisites all are.

        Main story milestones come first, otherwise YAML order.
        """
        open_ = [
            m
            for m in self.objectives.milestones
            if not state[m.id] and all(state[dep] for dep in m.requires)
        ]
        return sorted(open_, key=lambda m: MAIN_TAG not in m.tags)

    def capabilities(self, ram: Ram) -> set[str]:
        """Names of the capabilities the player has now, e.g. {"CUT"}."""
        return {
            name for name, p in self.objectives.capabilities.items() if p.evaluate(ram)
        }


def primary(frontier: list[Milestone]) -> Milestone | None:
    """Pick the current goal, the first milestone of the frontier."""
    return frontier[0] if frontier else None
