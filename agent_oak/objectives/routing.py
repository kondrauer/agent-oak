"""Plan a path from the player to a milestone's target."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from agent_oak.executor.dialogue import stand_tiles
from agent_oak.executor.graph import nearest_path
from agent_oak.executor.models import ELEVATOR, Edge, Node, World
from agent_oak.objectives.milestones import Milestone, Objectives
from agent_oak.objectives.predicates import Capability
from agent_oak.objectives.ram import Ram
from agent_oak.parser.models import GameMap

RouteStatus = Literal["route", "here", "blocked", "no_location", "no_path", "disabled"]
BOULDER_SPRITE = "SPRITE_BOULDER"
# a step the player can't take yet costs more than any detour, so the path
# only needs what can't be avoided, and more the further away the story is
# from opening it: per milestone still to do up to and including its opener.
# Where two ways lead on (Lavender: Route 9's tree or Route 12's Snorlax),
# the one that opens sooner wins.
MISSING_STEP_COST = 10_000.0
# what stands in the way when a path needs a capability
OBSTACLES = {
    "CUT": "a small tree, you need Cut (HM01) and the Cascade Badge",
    "SURF": "water, you need Surf (HM03) and the Soul Badge",
    "STRENGTH": "a boulder, you need Strength (HM04) and the Rainbow Badge",
}


@dataclass(frozen=True)
class RouteContext:
    """What the static map data does not know: sprites and story blockers."""

    blocked: frozenset[Node] = frozenset()
    """Tiles of NPCs that stand still and are shown, never passable."""
    gates: dict[Node, frozenset[str]] = field(default_factory=dict)
    """Tokens needed to enter a tile: STRENGTH for boulders, blocker ids."""
    reasons: dict[str, str] = field(default_factory=dict)
    """Why a token blocks, for capabilities and active blockers."""
    distance: dict[str, int] = field(default_factory=dict)
    """Milestones left until a token opens, unknown ones count as all."""
    default_distance: int = 1

    def gate(self, node: Node) -> frozenset[str]:
        """Tokens needed to enter 'node'."""
        return self.gates.get(node, frozenset())


def route_context(
    objectives: Objectives, maps: dict[str, GameMap], ram: Ram
) -> RouteContext:
    """Collect the sprites and blockers that are in the way right now.

    Item balls are left out, walking up to them picks them up. Objects
    hidden by the story (bit set in wToggleableObjectFlags) are gone.
    """
    blocked: set[Node] = set()
    gates: dict[Node, set[str]] = {}
    for const, game_map in maps.items():
        for obj in game_map.map_objects:
            if obj.movement != "STAY" or obj.kind == "item":
                continue
            toggle = objectives.toggle_by_object.get(obj.name or "")
            if toggle is not None and ram.bit("wToggleableObjectFlags", toggle):
                continue
            node: Node = (const, obj.x, obj.y)
            if obj.sprite == BOULDER_SPRITE:
                gates.setdefault(node, set()).add("STRENGTH")
            else:
                blocked.add(node)

    by_id = objectives.by_id()
    done = {m.id: m.done.evaluate(ram) for m in objectives.milestones}

    def left(milestone: str) -> int:
        """Milestones not done among 'milestone' and its prerequisites."""
        seen: set[str] = set()
        todo = [milestone]
        while todo:
            mid = todo.pop()
            if mid not in seen:
                seen.add(mid)
                todo.extend(by_id[mid].requires)
        # at least 1: a token that is missing is never free
        return max(1, sum(not done[mid] for mid in seen))

    openers = {
        m.done.name: m for m in objectives.milestones if isinstance(m.done, Capability)
    }
    distance = {name: left(m.id) for name, m in openers.items()}
    reasons = {
        name: text
        + (f" (opens with: {openers[name].label})" if name in openers else "")
        for name, text in OBSTACLES.items()
    }
    for blocker in objectives.blockers:
        if blocker.until.evaluate(ram):
            continue
        opener = by_id.get(blocker.opened_by or "")
        reasons[blocker.id] = blocker.blurb
        if opener is not None:
            distance[blocker.id] = left(opener.id)
            reasons[blocker.id] += f" (opens with: {opener.label})"
        for x, y in blocker.tiles:
            node = (blocker.map, x, y)
            # the blocker explains this tile, it opens with it
            blocked.discard(node)
            gates.setdefault(node, set()).add(blocker.id)

    return RouteContext(
        blocked=frozenset(blocked),
        gates={n: frozenset(t) for n, t in gates.items()},
        reasons=reasons,
        distance=distance,
        default_distance=len(objectives.milestones) + 1,
    )


class RouteTarget(BaseModel):
    """The milestone's target in step coordinates."""

    map: str
    x: int | None = None
    y: int | None = None
    kind: str | None = Field(
        default=None, description="npc, tile or warp, None to just enter the map"
    )
    name: str | None = Field(
        default=None, description="Object constant for npcs, destination for warps"
    )


class Route(BaseModel):
    """A planned path to the current goal, or why there is none."""

    status: RouteStatus = Field(
        description="route (path found), here (already there), blocked (a "
        "path needs what blocked_by lists), no_location (the goal has no "
        "place, e.g. a menu action), no_path or disabled (hints are off)"
    )
    milestone: str
    target: RouteTarget | None = None
    stand: Node | None = Field(
        default=None, description="Tile the path ends on (map, x, y)"
    )
    steps: int = 0
    maps: list[str] = Field(default_factory=list, description="Maps on the way")
    summary: str = ""
    blocked_by: list[str] = Field(
        default_factory=list,
        description="What the path needs that the player lacks: capabilities "
        "(CUT, SURF, STRENGTH) or story blockers",
    )
    blocked_reasons: list[str] = Field(
        default_factory=list, description="Why, one line per blocked_by entry"
    )


def _goal_tiles(world: World, milestone: Milestone) -> set[Node] | None:
    """Tiles that count as arrived, None for any tile of the milestone's map."""
    assert milestone.map is not None
    target = milestone.target
    if target is None:
        return None
    node: Node = (milestone.map, target.x, target.y)
    if target.kind == "warp":
        return set(world.doorway(node=node))
    if target.kind == "tile" and world.terrain(node=node) not in (None, "cut"):
        # a position triggered script, stand on it
        return {node}
    # an NPC or a hidden object on a solid tile, stand next to it
    return {stand for stand, _ in stand_tiles(world=world, target=node, occupied=set())}


def summarize(start: Node, path: list[Edge]) -> tuple[list[str], str]:
    """List the maps a path passes through and summarize it in one line."""
    maps = [start[0]]
    for edge in path:
        if edge.dst[0] != maps[-1]:
            maps.append(edge.dst[0])
    steps = f"{len(path)} step{'' if len(path) == 1 else 's'}"
    if len(maps) == 1:
        return maps, f"{steps} on {maps[0]}"
    return maps, f"{steps}: {' → '.join(maps)}"


def plan_route(
    world: World,
    milestone: Milestone,
    start: Node,
    abilities: Iterable[str] = (),
    context: RouteContext | None = None,
) -> Route:
    """Find the shortest path from 'start' to the milestone's target.

    Searches with the player's capabilities first. When that finds nothing,
    searches again as if every capability and story blocker were cleared,
    with steps that need one costing far more than any detour, and reports
    what that path needs in blocked_by. Only NPCs that stand
    still are avoided, goto replans around the others when walking.

    Args:
        world: The world model used for pathfinding.
        milestone: The milestone to go to.
        start: The player's position.
        abilities: Capabilities the player has, e.g. {"SURF"}.
        context: Sprites and story blockers in the way right now.
    Returns:
        The route, or why there is none.
    """
    if milestone.map is None:
        return Route(status="no_location", milestone=milestone.id)

    t = milestone.target
    target = RouteTarget(
        map=milestone.map,
        x=t.x if t else None,
        y=t.y if t else None,
        kind=t.kind if t else None,
        name=t.name if t else None,
    )
    goals = _goal_tiles(world=world, milestone=milestone)
    map_const = milestone.map
    ctx = context or RouteContext()
    # the route is a plan, it may say to ride an elevator
    have = frozenset(abilities) | {ELEVATOR}

    def is_goal(node: Node) -> bool:
        return node[0] == map_const if goals is None else node in goals

    def missing_cost(needs: frozenset[str]) -> float:
        return MISSING_STEP_COST * sum(
            ctx.distance.get(token, ctx.default_distance) for token in needs - have
        )

    def gate(node: Node) -> frozenset[str]:
        # a blocker on the goal is what the goal is about (the ghost on the
        # stairs is beaten there), it doesn't keep the player from it
        if goals is not None and node in goals:
            return frozenset()
        return ctx.gate(node)

    def search(tokens: frozenset[str]) -> list[Edge] | None:
        return nearest_path(
            world=world,
            start=start,
            is_goal=is_goal,
            abilities=tokens,
            blocked=lambda n: n in ctx.blocked,
            gates=gate,
            penalty=missing_cost,
        )

    path = search(have)
    missing: list[str] = []
    if path is None:
        everything = have | set(ctx.reasons)
        for tokens in ctx.gates.values():
            everything |= tokens
        path = search(frozenset(everything))
        if path is None:
            return Route(status="no_path", milestone=milestone.id, target=target)
        used: set[str] = set()
        for edge in path:
            used |= edge.requires | gate(edge.dst)
        missing = sorted(used - have)

    maps, summary = summarize(start=start, path=path)
    if missing:
        status: RouteStatus = "blocked"
        summary = f"blocked by {', '.join(missing)}, {summary}"
    else:
        status = "route" if path else "here"
    return Route(
        status=status,
        milestone=milestone.id,
        target=target,
        stand=path[-1].dst if path else start,
        steps=len(path),
        maps=maps,
        summary=summary if path else "already there",
        blocked_by=missing,
        blocked_reasons=[f"{m}: {ctx.reasons.get(m, m)}" for m in missing],
    )
