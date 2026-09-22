"""Module to build a world graph."""

from networkx import MultiDiGraph

from agent_oak.executor.models import OPPOSITE, World
from agent_oak.parser.maps import parse_maps
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


if __name__ == "__main__":
    by_str, by_id = parse_maps()

    print(resolve_last_map(by_str))
