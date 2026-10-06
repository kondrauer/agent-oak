"""Predicates over a RAM snapshot, the building blocks of milestones.

Names (EVENT_BEAT_MISTY, CASCADE, SS_TICKET, ...) are resolved to RAM
indices once, when the YAML is parsed, so typos fail at startup and
evaluation is only bit tests.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agent_oak.objectives.ram import Ram


class Predicate(Protocol):
    """Something that is true or false for a RAM snapshot."""

    def evaluate(self, ram: Ram) -> bool:
        """Whether it holds in 'ram'."""
        ...

    def describe(self) -> str:
        """Short human readable form, e.g. "has badge CASCADE"."""
        ...


@dataclass(frozen=True)
class EventFlag:
    """An event flag is set, a bit of wEventFlags."""

    name: str
    index: int

    def evaluate(self, ram: Ram) -> bool:
        """Test the flag's bit."""
        return ram.bit("wEventFlags", self.index)

    def describe(self) -> str:
        """E.g. "EVENT_BEAT_MISTY"."""
        return self.name


@dataclass(frozen=True)
class Badge:
    """A badge is obtained, a bit of wObtainedBadges."""

    name: str
    bit: int

    def evaluate(self, ram: Ram) -> bool:
        """Test the badge's bit."""
        return ram.bit("wObtainedBadges", self.bit)

    def describe(self) -> str:
        """E.g. "CASCADE badge"."""
        return f"{self.name} badge"


@dataclass(frozen=True)
class ItemInBag:
    """An item is in the bag, or with 'anywhere' in the bag or the PC."""

    name: str
    item_id: int
    anywhere: bool = False

    def evaluate(self, ram: Ram) -> bool:
        """Look for the item id in the bag (and PC) lists."""
        if self.item_id in ram.bag_items():
            return True
        return self.anywhere and self.item_id in ram.box_items()

    def describe(self) -> str:
        """E.g. "S_S_TICKET in bag"."""
        return f"{self.name} in {'bag or PC' if self.anywhere else 'bag'}"


@dataclass(frozen=True)
class TownVisited:
    """A town was entered once, a bit of wTownVisitedFlag (Fly targets)."""

    name: str
    bit: int

    def evaluate(self, ram: Ram) -> bool:
        """Test the town's bit."""
        return ram.bit("wTownVisitedFlag", self.bit)

    def describe(self) -> str:
        """E.g. "visited CERULEAN_CITY"."""
        return f"visited {self.name}"


@dataclass(frozen=True)
class ObjectHidden:
    """A toggleable object is hidden, a bit of wToggleableObjectFlags."""

    name: str
    index: int

    def evaluate(self, ram: Ram) -> bool:
        """Test the object's bit, a set bit hides it."""
        return ram.bit("wToggleableObjectFlags", self.index)

    def describe(self) -> str:
        """E.g. "TOGGLE_NUGGET_BRIDGE_GUY hidden"."""
        return f"{self.name} hidden"


@dataclass(frozen=True)
class PartyMove:
    """Any party Pokemon knows a move."""

    name: str
    move_id: int

    def evaluate(self, ram: Ram) -> bool:
        """Look for the move id in every party Pokemon's moves."""
        return self.move_id in ram.party_moves()

    def describe(self) -> str:
        """E.g. "party knows CUT"."""
        return f"party knows {self.name}"


@dataclass(frozen=True)
class Capability:
    """A named predicate from the YAML's capabilities, e.g. CUT."""

    name: str
    predicate: Predicate

    def evaluate(self, ram: Ram) -> bool:
        """Evaluate the capability's definition."""
        return self.predicate.evaluate(ram)

    def describe(self) -> str:
        """E.g. "can use CUT"."""
        return f"can use {self.name}"


@dataclass(frozen=True)
class All:
    """Every predicate holds."""

    predicates: tuple[Predicate, ...]

    def evaluate(self, ram: Ram) -> bool:
        """Check that all hold, true for none."""
        return all(p.evaluate(ram) for p in self.predicates)

    def describe(self) -> str:
        """Join the parts with "and"."""
        return " and ".join(p.describe() for p in self.predicates)


@dataclass(frozen=True)
class Any_:
    """At least one predicate holds."""

    predicates: tuple[Predicate, ...]

    def evaluate(self, ram: Ram) -> bool:
        """Check that at least one holds."""
        return any(p.evaluate(ram) for p in self.predicates)

    def describe(self) -> str:
        """Join the parts with "or"."""
        return "(" + " or ".join(p.describe() for p in self.predicates) + ")"


@dataclass(frozen=True)
class Not:
    """The predicate does not hold."""

    predicate: Predicate

    def evaluate(self, ram: Ram) -> bool:
        """Negate the inner predicate."""
        return not self.predicate.evaluate(ram)

    def describe(self) -> str:
        """E.g. "not TOGGLE_X hidden"."""
        return f"not {self.predicate.describe()}"


class PredicateError(ValueError):
    """A predicate in the YAML is malformed or names something unknown."""


class PredicateParser:
    """Build predicates from their YAML form, resolving names to RAM indices.

    Unknown names are collected in 'errors' instead of raising right away, so
    one load reports every typo at once.
    """

    def __init__(
        self,
        constants: dict[str, Any],
        capabilities: dict[str, Predicate] | None = None,
    ) -> None:
        """Use the tables of data/constants.json to resolve names.

        Args:
            constants: The tables written by write_constants.
            capabilities: Capabilities parsed so far, for `capability: CUT`.
        """
        self.constants = constants
        self.capabilities = capabilities if capabilities is not None else {}
        self.errors: list[str] = []

    def _lookup(self, table: str, name: Any, where: str) -> int:
        value = self.constants[table].get(name) if isinstance(name, str) else None
        if value is None:
            self.errors.append(f"{where}: unknown {table[:-1]} {name!r}")
            return -1
        return value

    def _list(self, value: Any, where: str) -> tuple[Predicate, ...]:
        if not isinstance(value, list) or not value:
            self.errors.append(f"{where}: expected a non-empty list, got {value!r}")
            return ()
        return tuple(self.parse(v, where) for v in value)

    def parse(self, spec: Any, where: str) -> Predicate:
        """Parse one predicate, e.g. {"badge": "CASCADE"}.

        Args:
            spec: The YAML value, a mapping with exactly one key.
            where: Where it is in the YAML, for error messages.
        Returns:
            The predicate. With errors it is a placeholder so parsing can go
                on, check 'errors' and do not evaluate it.
        """
        if not isinstance(spec, dict) or len(spec) != 1:
            self.errors.append(f"{where}: expected a mapping with one key: {spec!r}")
            return All(())
        ((kind, value),) = spec.items()
        here = f"{where}.{kind}"

        builders: dict[str, Callable[[], Predicate]] = {
            "event": lambda: EventFlag(value, self._lookup("events", value, here)),
            "badge": lambda: Badge(value, self._lookup("badges", value, here)),
            "item": lambda: ItemInBag(value, self._lookup("items", value, here)),
            "item_anywhere": lambda: ItemInBag(
                value, self._lookup("items", value, here), anywhere=True
            ),
            "visited": lambda: TownVisited(value, self._lookup("towns", value, here)),
            "object_hidden": lambda: ObjectHidden(value, self._toggle(value, here)),
            "party_move": lambda: PartyMove(value, self._lookup("moves", value, here)),
            "capability": lambda: self._capability(value, here),
            "all": lambda: All(self._list(value, here)),
            "any": lambda: Any_(self._list(value, here)),
            "not": lambda: Not(self.parse(value, here)),
        }
        builder = builders.get(kind)
        if builder is None:
            self.errors.append(
                f"{where}: unknown predicate {kind!r}, expected one of "
                f"{', '.join(builders)}"
            )
            return All(())
        return builder()

    def _toggle(self, name: Any, where: str) -> int:
        entry = self.constants["toggles"].get(name) if isinstance(name, str) else None
        if entry is None:
            self.errors.append(f"{where}: unknown toggleable object {name!r}")
            return -1
        return entry["index"]

    def _capability(self, name: Any, where: str) -> Predicate:
        predicate = self.capabilities.get(name) if isinstance(name, str) else None
        if predicate is None:
            self.errors.append(f"{where}: unknown capability {name!r}")
            return All(())
        return Capability(name, predicate)
