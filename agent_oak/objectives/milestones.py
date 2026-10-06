"""Load and validate the milestone DAG from data/objectives.yaml."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_oak.objectives.constants import load_constants_json
from agent_oak.objectives.predicates import Predicate, PredicateParser
from agent_oak.parser.models import GameMap, MapObject

OBJECTIVES_PATH = Path("data/objectives.yaml")
MILESTONE_KEYS = {
    "id",
    "label",
    "done",
    "requires",
    "map",
    "target",
    "blurb",
    "readiness",
    "tags",
}
READINESS_KEYS = {"min_level", "ace", "ace_level"}
BLOCKER_KEYS = {"id", "map", "tiles", "npcs", "until", "blurb"}


@dataclass(frozen=True)
class Target:
    """Where on the milestone's map to go, resolved to step coordinates."""

    x: int
    y: int
    kind: str
    """npc, tile or warp."""
    name: str | None = None
    """Object constant for npc targets, destination map for warps."""


@dataclass(frozen=True)
class Readiness:
    """Soft checks before attempting a milestone, e.g. a gym leader's ace."""

    min_level: int | None = None
    ace: str | None = None
    ace_level: int | None = None


@dataclass(frozen=True)
class Milestone:
    """A story step with a RAM predicate that tells whether it is done."""

    id: str
    label: str
    done: Predicate
    blurb: str
    requires: tuple[str, ...] = ()
    map: str | None = None
    target: Target | None = None
    readiness: Readiness = field(default_factory=Readiness)
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Blocker:
    """Tiles a script or NPC keeps the player off until a predicate holds.

    E.g. the old man north of Viridian City until the Pokedex, the guard in
    front of the robbed house in Cerulean until the S.S. Ticket.
    """

    id: str
    map: str
    tiles: tuple[tuple[int, int], ...]
    until: Predicate
    blurb: str


@dataclass(frozen=True)
class Objectives:
    """Every milestone in YAML order, the capabilities and the blockers."""

    milestones: tuple[Milestone, ...]
    capabilities: dict[str, Predicate]
    blockers: tuple[Blocker, ...] = ()
    toggle_by_object: dict[str, int] = field(default_factory=dict)
    """Toggleable object index by object constant, e.g. CERULEANCITY_GUARD2."""

    def by_id(self) -> dict[str, Milestone]:
        """Milestones keyed by id."""
        return {m.id: m for m in self.milestones}


class ObjectivesError(ValueError):
    """The YAML has problems, the message lists all of them."""

    def __init__(self, problems: list[str]) -> None:
        """Keep the problems for tests and list them in the message."""
        self.problems = problems
        super().__init__(
            f"{len(problems)} problem(s) in the objectives:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


def _find_npc(
    game_map: GameMap, name: Any, where: str, errors: list[str]
) -> MapObject | None:
    """Find the one object on 'game_map' called 'name', with or without prefix."""
    found = [
        o
        for o in game_map.map_objects
        if o.name is not None and (o.name == name or o.name.endswith(f"_{name}"))
    ]
    if len(found) != 1:
        names = [o.name for o in game_map.map_objects]
        errors.append(
            f"{where}: npc {name!r} matches {len(found)} objects on "
            f"{game_map.const}, objects are {names}"
        )
        return None
    return found[0]


def _parse_blocker(
    raw: Any,
    index: int,
    parser: PredicateParser,
    maps: dict[str, GameMap],
    errors: list[str],
) -> Blocker | None:
    where = f"blockers[{index}]"
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        errors.append(f"{where}: expected a mapping with an id")
        return None
    where = f"blockers.{raw['id']}"
    for key in raw.keys() - BLOCKER_KEYS:
        errors.append(f"{where}: unknown key {key!r}")
    for key in ("map", "until", "blurb"):
        if key not in raw:
            errors.append(f"{where}: missing {key}")
    game_map = maps.get(raw.get("map", ""))
    if game_map is None:
        errors.append(f"{where}.map: unknown map {raw.get('map')!r}")
        return None

    tiles: list[tuple[int, int]] = []
    for tile in raw.get("tiles") or []:
        if (
            not isinstance(tile, list)
            or len(tile) != 2
            or not (0 <= tile[0] < game_map.step_width)
            or not (0 <= tile[1] < game_map.step_height)
        ):
            errors.append(f"{where}.tiles: {tile!r} is not an [x, y] on the map")
            continue
        tiles.append((tile[0], tile[1]))
    for name in raw.get("npcs") or []:
        npc = _find_npc(game_map, name, f"{where}.npcs", errors)
        if npc is not None:
            tiles.append((npc.x, npc.y))
    if not tiles:
        errors.append(f"{where}: needs tiles or npcs")

    return Blocker(
        id=raw["id"],
        map=game_map.const,
        tiles=tuple(tiles),
        until=parser.parse(raw.get("until"), f"{where}.until"),
        blurb=str(raw.get("blurb", "")),
    )


def _resolve_target(
    spec: Any,
    map_const: str | None,
    maps: dict[str, GameMap],
    where: str,
    errors: list[str],
) -> Target | None:
    if spec is None:
        return None
    if map_const is None or map_const not in maps:
        errors.append(f"{where}: a target needs a known map")
        return None
    if not isinstance(spec, dict) or len(spec) != 1:
        errors.append(f"{where}: expected one of npc, tile or warp: {spec!r}")
        return None
    game_map = maps[map_const]
    ((kind, value),) = spec.items()

    if kind == "npc":
        found = _find_npc(game_map, value, where, errors)
        if found is None:
            return None
        return Target(x=found.x, y=found.y, kind="npc", name=found.name)

    if kind == "tile":
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(v, int) for v in value)
        ):
            errors.append(f"{where}: tile must be [x, y], got {value!r}")
            return None
        x, y = value
        if not (0 <= x < game_map.step_width and 0 <= y < game_map.step_height):
            errors.append(f"{where}: tile {value} is outside {map_const}")
            return None
        return Target(x=x, y=y, kind="tile")

    if kind == "warp":
        warps = [w for w in game_map.warps if w.dest_map == value]
        if not warps:
            errors.append(f"{where}: no warp from {map_const} to {value!r}")
            return None
        return Target(x=warps[0].x, y=warps[0].y, kind="warp", name=value)

    errors.append(f"{where}: unknown target kind {kind!r}")
    return None


def _check_acyclic(milestones: list[Milestone], errors: list[str]) -> None:
    known = {m.id: m for m in milestones}
    state: dict[str, str] = {}  # visiting / done

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == "done":
            return
        if state.get(node) == "visiting":
            cycle = path[path.index(node) :] + [node]
            errors.append(f"requires form a cycle: {' -> '.join(cycle)}")
            return
        state[node] = "visiting"
        for dep in known[node].requires:
            if dep in known:
                visit(dep, path + [node])
        state[node] = "done"

    for m in milestones:
        visit(m.id, [])


def parse_objectives(
    data: Any,
    constants: dict[str, Any],
    maps: dict[str, GameMap],
) -> Objectives:
    """Build and validate the objectives from their parsed YAML.

    Args:
        data: The YAML document, with 'capabilities' and 'milestones'.
        constants: The tables of data/constants.json.
        maps: Parsed game maps keyed by const, to resolve targets.
    Returns:
        The objectives.
    Raises:
        ObjectivesError: Listing every problem found, unknown names,
            unknown or cyclic requires, unresolvable targets, ...
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ObjectivesError(["the document must be a mapping"])

    capabilities: dict[str, Predicate] = {}
    parser = PredicateParser(constants=constants, capabilities=capabilities)
    for name, spec in (data.get("capabilities") or {}).items():
        capabilities[name] = parser.parse(spec, f"capabilities.{name}")

    milestones: list[Milestone] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("milestones") or []):
        where = f"milestones[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        mid = raw.get("id")
        if not isinstance(mid, str):
            errors.append(f"{where}: missing id")
            continue
        where = f"{mid}"
        if mid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(mid)
        for key in raw.keys() - MILESTONE_KEYS:
            errors.append(f"{where}: unknown key {key!r}")
        for key in ("label", "done", "blurb"):
            if key not in raw:
                errors.append(f"{where}: missing {key}")

        map_const = raw.get("map")
        if map_const is not None and map_const not in constants["maps"]:
            errors.append(f"{where}.map: unknown map {map_const!r}")
            map_const = None

        readiness_raw = raw.get("readiness") or {}
        for key in readiness_raw.keys() - READINESS_KEYS:
            errors.append(f"{where}.readiness: unknown key {key!r}")
        ace = readiness_raw.get("ace")
        if ace is not None and ace not in constants["species"]:
            errors.append(f"{where}.readiness.ace: unknown species {ace!r}")

        requires = raw.get("requires") or []
        if not isinstance(requires, list):
            errors.append(f"{where}.requires: expected a list")
            requires = []

        milestones.append(
            Milestone(
                id=mid,
                label=str(raw.get("label", mid)),
                done=parser.parse(raw.get("done"), f"{where}.done"),
                blurb=str(raw.get("blurb", "")),
                requires=tuple(requires),
                map=map_const,
                target=_resolve_target(
                    raw.get("target"), map_const, maps, f"{where}.target", errors
                ),
                readiness=Readiness(
                    min_level=readiness_raw.get("min_level"),
                    ace=ace,
                    ace_level=readiness_raw.get("ace_level"),
                ),
                tags=tuple(raw.get("tags") or ()),
            )
        )

    blockers = []
    for i, raw in enumerate(data.get("blockers") or []):
        blocker = _parse_blocker(raw, i, parser, maps, errors)
        if blocker is not None:
            blockers.append(blocker)
    ids = [b.id for b in blockers]
    for dup in {b for b in ids if ids.count(b) > 1}:
        errors.append(f"blockers.{dup}: duplicate id")

    for m in milestones:
        for dep in m.requires:
            if dep not in seen:
                errors.append(f"{m.id}.requires: unknown milestone {dep!r}")
    _check_acyclic(milestones, errors)

    errors = parser.errors + errors
    if errors:
        raise ObjectivesError(errors)
    return Objectives(
        milestones=tuple(milestones),
        capabilities=capabilities,
        blockers=tuple(blockers),
        toggle_by_object={
            t["object"]: t["index"] for t in constants["toggles"].values()
        },
    )


def load_objectives(
    maps: dict[str, GameMap],
    path: Path = OBJECTIVES_PATH,
    constants: dict[str, Any] | None = None,
) -> Objectives:
    """Load data/objectives.yaml, fails loudly on any problem.

    Args:
        maps: Parsed game maps keyed by const, to resolve targets.
        path: The YAML file.
        constants: The constant tables, defaults to data/constants.json.
    Returns:
        The validated objectives.
    """
    return parse_objectives(
        data=yaml.safe_load(path.read_text()),
        constants=constants if constants is not None else load_constants_json(),
        maps=maps,
    )
