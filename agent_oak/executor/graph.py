"""Module to build a world graph."""

import heapq
from typing import Callable, Iterable

from networkx import MultiDiGraph

from agent_oak.executor.models import OPPOSITE, Edge, Node, World
from agent_oak.parser.maps import parse_maps, parse_tilesets
from agent_oak.parser.models import Direction, GameMap


def build_game_map_graph(game_maps: dict[str, GameMap]) -> MultiDiGraph:
    """Build a graph out of the game_maps dict."""
    G = MultiDiGraph()

    for m in game_maps.values():
        G.add_node(m.const, model=m)

        for c in m.connections:
            G.add_edge(
                m.const,
                c.target_const,
                kind="connection",
                direction=c.direction,
                offset=c.offset,
            )

        for i, w in enumerate(m.warps):
            if w.dest_map != "LAST_MAP":
                G.add_edge(
                    m.const,
                    w.dest_map,
                    kind="warp",
                    src_warp=i,
                    dest_warp=w.dest_warp,
                    x=w.x,
                    y=w.y,
                )

    return G


def check_connection_offsets(maps: dict[str, GameMap]) -> list[str]:
    """Sanity check if connection offsets match.

    Every connection should have a reciprocal one with the negated offset.
    Catches sign errors and dropped lines in the header parser.
    """
    problems: list[str] = []
    for const, m in maps.items():
        for c in m.connections:
            t = maps.get(c.target_const)
            if t is None:
                problems.append(f"{const} -> {c.target_const}: target not parsed")
                continue
            back = [
                b
                for b in t.connections
                if b.target_const == const
                and Direction(b.direction) is OPPOSITE[Direction(c.direction)]
            ]
            if not back:
                problems.append(
                    f"{const} {c.direction} {c.target_const}: no reciprocal"
                )
            elif back[0].offset != -c.offset:
                problems.append(
                    f"{const} {c.direction} {c.target_const}: offset {c.offset} "
                    f"vs reciprocal {back[0].offset}"
                )
    return problems


def check_crossings(world: World) -> list[str]:
    """Sanity check for world crossings.

    Walk off every edge of every map and confirm you land in bounds.
    A wrong offset sign shows up here as out-of-range landings on the
    asymmetric pairs, while the symmetric (offset 0) ones stay silent.
    """
    problems: list[str] = []
    for const, m in world.maps.items():
        for d, conn in world._conns[const].items():
            axis = (
                range(m.width * 2)
                if d in (Direction.NORTH, Direction.SOUTH)
                else range(m.height * 2)
            )
            landed = 0
            for i in axis:
                _ = (
                    (const, i, 0)
                    if d in (Direction.NORTH, Direction.SOUTH)
                    else (const, 0, i)
                )
                x, y = (i, 0) if d in (Direction.NORTH, Direction.SOUTH) else (0, i)
                dst = world._cross(conn, d, x, y)
                if world.in_bounds(dst):
                    landed += 1
            if landed == 0:
                problems.append(
                    f"{const} {d.value} -> {conn.target_const}: "
                    f"no in-bounds landing, offset {conn.offset}"
                )
    return problems


def resolve_last_map(maps: dict[str, GameMap]) -> dict[str, set[str]]:
    """Get possible LAST_MAP warps for every map.

    LAST_MAP warps mean 'back where you came from'. Statically, that is the
    set of maps that warp *into* this one. Use it as the edge fan-out, or carry
    the previous map in your search state for an exact answer.
    """
    inbound: dict[str, set[str]] = {k: set() for k in maps}
    for const, m in maps.items():
        for w in m.warps:
            if w.dest_map in inbound:
                inbound[w.dest_map].add(const)
    return inbound


def shortest_path(
    world: World,
    start: Node,
    goal: Node,
    abilities: Iterable[str] = (),
    blocked: Callable[[Node], bool] = lambda n: False,
    heuristic: Callable[[Node, Node], float] | None = None,
) -> list[Edge] | None:
    """Search with A* over the lazy neighbour function.

    `abilities` are the tokens that satisfy edge `requires` ({'SURF', 'CUT', ...}).
    `blocked` is where sprites go -- pass a closure over your RAM overlay, or over
    the static object models filtered by progression.
    """
    have = frozenset(abilities)
    h = heuristic or (lambda a, b: 0.0)
    seen: set[Node] = set()
    best: dict[Node, float] = {start: 0.0}
    prev: dict[Node, tuple[Node, Edge]] = {}
    pq: list[tuple[float, int, Node]] = [(h(start, goal), 0, start)]
    tick = 0

    while pq:
        _, _, cur = heapq.heappop(pq)
        if cur == goal:
            out: list[Edge] = []
            while cur in prev:
                cur, e = prev[cur]
                out.append(e)
            return out[::-1]
        if cur in seen:
            continue
        seen.add(cur)

        for e in world.neighbors(node=cur):
            if e.requires > have or blocked(e.dst):
                continue

            g = best[cur] + e.cost
            if g < best.get(e.dst, float("inf")):
                best[e.dst] = g
                prev[e.dst] = (cur, e)
                tick += 1
                heapq.heappush(pq, (g + h(e.dst, goal), tick, e.dst))

    return None


if __name__ == "__main__":
    maps_by_str, _ = parse_maps()
    tilesets_by_str, _ = parse_tilesets()

    world = World(maps=maps_by_str, tilesets=tilesets_by_str)
