"""Plan a path from the player to a milestone's target."""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from agent_oak.executor.dialogue import stand_tiles
from agent_oak.executor.graph import nearest_path
from agent_oak.executor.models import Edge, Node, World
from agent_oak.objectives.milestones import Milestone

RouteStatus = Literal["route", "here", "no_location", "no_path"]


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
        description="route (path found), here (already there), no_location "
        "(the goal has no place, e.g. a menu action) or no_path"
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
        default_factory=list, description="Capabilities the path is missing"
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
    if target.kind == "tile" and world.terrain(node=node) is not None:
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
) -> Route:
    """Find the shortest path from 'start' to the milestone's target.

    NPC positions are ignored, goto replans around them when walking.

    Args:
        world: The world model used for pathfinding.
        milestone: The milestone to go to.
        start: The player's position.
        abilities: Capabilities the player has, e.g. {"SURF"}.
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

    def is_goal(node: Node) -> bool:
        return node[0] == map_const if goals is None else node in goals

    path = nearest_path(world=world, start=start, is_goal=is_goal, abilities=abilities)
    if path is None:
        return Route(status="no_path", milestone=milestone.id, target=target)

    maps, summary = summarize(start=start, path=path)
    return Route(
        status="route" if path else "here",
        milestone=milestone.id,
        target=target,
        stand=path[-1].dst if path else start,
        steps=len(path),
        maps=maps,
        summary=summary if path else "already there",
    )
