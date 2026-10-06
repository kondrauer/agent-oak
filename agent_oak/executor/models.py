"""Models for executor module."""

from typing import Iterator, Literal

from pydantic import BaseModel, Field

from agent_oak.memory.models import DialogueResult
from agent_oak.parser.models import Connection, Direction, GameMap, Tileset

DELTA: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (0, -1),
    Direction.SOUTH: (0, 1),
    Direction.WEST: (-1, 0),
    Direction.EAST: (1, 0),
}

OPPOSITE: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

Node = tuple[str, int, int]

# elevators go to a floor picked in a menu, goto can't do that, routing can
ELEVATOR = "ELEVATOR"

GotoStatus = Literal["reached", "in_battle", "dialogue_open", "no_path", "gave_up"]

# tilesets pokered's CheckIfInOutsideMap treats as outside
OUTDOOR_TILESETS = frozenset({"OVERWORLD", "PLATEAU"})

# LAST_MAP warps where wLastMap is set by a map script instead of by warping.
# Route22Gate's script picks ROUTE_22 or ROUTE_23 from the player's y, so
# the south doors lead to route 22 and the north doors to route 23.
LAST_MAP_OVERRIDES: dict[tuple[str, int], str] = {
    ("ROUTE_22_GATE", 0): "ROUTE_22",
    ("ROUTE_22_GATE", 1): "ROUTE_22",
    ("ROUTE_22_GATE", 2): "ROUTE_23",
    ("ROUTE_22_GATE", 3): "ROUTE_23",
}


def resolve_last_map(maps: dict[str, GameMap]) -> dict[str, set[str]]:
    """Get possible LAST_MAP targets for every map.

    LAST_MAP warps lead to wLastMap, which the game only updates when warping
    out of an outdoor map. Statically, that is the set of outdoor maps that
    warp *into* this one, which is exactly one map for every LAST_MAP warp
    except those in LAST_MAP_OVERRIDES.
    """
    inbound: dict[str, set[str]] = {k: set() for k in maps}
    for const, m in maps.items():
        if m.tileset not in OUTDOOR_TILESETS:
            continue
        for w in m.warps:
            if w.dest_map in inbound:
                inbound[w.dest_map].add(const)
    return inbound


class Edge(BaseModel):
    """Edge in the world class."""

    dst: Node
    kind: Literal["walk", "ledge", "connection", "warp"]
    direction: Direction | None = None
    requires: frozenset[str] = frozenset()
    cost: float = 1.0


class TalkResult(BaseModel):
    """Outcome of walking up to something and talking to it."""

    walk: GotoStatus = Field(
        description="reached, or why the player could not get next to the target"
    )
    dialogue: DialogueResult | None = Field(
        default=None, description="Set when the conversation was started"
    )


class World:
    """Representation of the game world."""

    def __init__(
        self,
        maps: dict[str, GameMap],
        tilesets: dict[str, Tileset],
        connection_offset_sign: int = -1,
    ) -> None:
        """Initialize the world class."""
        self.maps = maps
        self.tilesets = tilesets
        self.sign = connection_offset_sign
        self._warps_out: dict[Node, list[Edge]] = {}
        # (x, y) of every warp tile leading into a map, keyed by that map
        self._warp_sources_into: dict[str, set[tuple[int, int]]] = {}
        self._conns: dict[str, dict[Direction, Connection]] = {}
        self._index()

    def _index(self) -> None:
        last_map = resolve_last_map(self.maps)
        for const, m in self.maps.items():
            self._conns[const] = {Direction(c.direction): c for c in m.connections}
            for floor in m.elevator_floors:
                dest = self.maps[floor.dest_map]
                dw = dest.warps[self._warp_index(floor.dest_warp)]
                for w in m.warps:
                    self._warps_out.setdefault((const, w.x, w.y), []).append(
                        Edge(
                            dst=(floor.dest_map, dw.x, dw.y),
                            kind="warp",
                            requires=frozenset({ELEVATOR}),
                        )
                    )
            for i, w in enumerate(m.warps):
                if w.dest_map == "LAST_MAP":
                    override = LAST_MAP_OVERRIDES.get((const, i))
                    targets = {override} if override else last_map[const]
                else:
                    targets = {w.dest_map}

                for target in targets:
                    dest = self.maps.get(target)
                    if dest is None:
                        print(f"Dest map {target} not found for warp {w}")
                        continue
                    idx = self._warp_index(w.dest_warp)
                    if not 0 <= idx < len(dest.warps):
                        print(f"Dest warp {w.dest_warp} not in {target} for warp {w}")
                        continue
                    dw = dest.warps[idx]
                    src: Node = (const, w.x, w.y)
                    self._warp_sources_into.setdefault(target, set()).add((w.x, w.y))
                    self._warps_out.setdefault(src, []).append(
                        Edge(
                            dst=(target, dw.x, dw.y),
                            kind="warp",
                            cost=1.0,
                        )
                    )

    @staticmethod
    def _warp_index(dest_warp: int) -> int:
        """Convert 1 based warp indices to 0 based.

        pokered's warp_event destination index. Newer syntax is 1-based;
        some older checkouts are 0-based. Verify against a known pair (e.g.
        PALLET_TOWN <-> REDS_HOUSE_1F) and flip this if the doors land wrong.
        """
        return dest_warp - 1

    @staticmethod
    def _pair_blocked(tileset: Tileset, terrain: str, a: int, b: int) -> bool:
        table = (
            tileset.pair_collisions_water
            if terrain == "water"
            else tileset.pair_collisions_land
        )
        return frozenset((a, b)) in table

    @staticmethod
    def _req(a: str | None, b: str | None) -> frozenset[str]:
        """Capabilities needed to step from terrain 'a' onto terrain 'b'."""
        if b == "cut":
            return frozenset({"CUT"})
        return frozenset({"SURF"}) if "water" in (a, b) else frozenset()

    def warp_destinations(self, node: Node) -> set[Node]:
        """Where the warp on 'node' leads, empty if there is no warp."""
        return {e.dst for e in self._warps_out.get(node, ())}

    def doorway(self, node: Node) -> list[Node]:
        """Get the warp tiles of the doorway 'node' belongs to, 'node' first.

        Doorways are two warps wide, adjacent warps to the same map. Not all
        of them can be taken: a gate exit only warps from the tile in front
        of its door graphic, the other half is wall.
        """
        const, x, y = node
        dest = {w.dest_map for w in self.maps[const].warps if (w.x, w.y) == (x, y)}
        if not dest:
            return [node]
        tiles = {(w.x, w.y) for w in self.maps[const].warps if w.dest_map in dest}
        group, todo = [node], [(x, y)]
        while todo:
            cx, cy = todo.pop()
            for dx, dy in DELTA.values():
                n = (cx + dx, cy + dy)
                if n in tiles and (const, *n) not in group:
                    group.append((const, *n))
                    todo.append(n)
        return group

    def in_bounds(self, node: Node) -> bool:
        """Check if a node is in bounds."""
        const, x, y = node
        m = self.maps.get(const)
        if m is None:
            return False

        return 0 <= x < m.step_width and 0 <= y < m.step_height

    def maybe_mid_warp(self, node: Node) -> bool:
        """Whether 'node' could be a half written position during a warp.

        The game sets wCurMap as soon as a warp is taken but only writes the
        destination x, y after the fade, so for a while the position reads as
        the new map with the coordinates of the warp tile it was entered from.
        """
        const, x, y = node
        return not self.in_bounds(node) or (x, y) in self._warp_sources_into.get(
            const, ()
        )

    def collision_tile(
        self,
        node: Node,
    ) -> int:
        """Tile id that decides passability (bottom left per quadrant in block)."""
        const, x, y = node
        m = self.maps[const]
        ts = self.tilesets[m.tileset]
        # convert from step to block coordinates
        block = m.blocks[(y // 2) * m.width + (x // 2)]
        # get current quadrant in block
        qx, qy = x % 2, y % 2
        # get tile id of bottom left tile in quadrant
        idx = block * 16 + (2 * qy + 1) * 4 + 2 * qx
        return ts.blocks[idx]

    def terrain(
        self,
        node: Node,
    ) -> str | None:
        """'land', 'water', 'cut' (a tree Cut removes) or None if solid."""
        if not self.in_bounds(node):
            return None

        ts = self.tilesets[self.maps[node[0]].tileset]
        t = self.collision_tile(node=node)
        if t in ts.collision:
            return "land"
        if t in ts.water:
            return "water"
        if t in ts.cut_trees:
            return "cut"
        return None

    def _cross(
        self,
        connection: Connection,
        d: Direction,
        x: int,
        y: int,
    ) -> Node:
        t = self.maps[connection.target_const]
        shift = self.sign * 2 * connection.offset
        if d is Direction.NORTH:
            return (t.const, x + shift, t.step_height - 1)
        if d is Direction.SOUTH:
            return (t.const, x + shift, 0)
        if d is Direction.WEST:
            return (t.const, t.step_width - 1, y + shift)
        return (t.const, 0, y + shift)

    def _ledge(
        self,
        tileset: Tileset,
        direction: Direction,
        standing: int,
        ledge_node: Node,
    ) -> Node | None:
        ledge_tile = self.collision_tile(node=ledge_node)
        if (direction, standing, ledge_tile) not in tileset.ledges:
            return None

        dx, dy = DELTA[direction]
        landing = (ledge_node[0], ledge_node[1] + dx, ledge_node[2] + dy)
        return landing if self.terrain(node=landing) == "land" else None

    def neighbors(self, node: Node) -> Iterator[Edge]:
        """All static edges out of 'node'."""
        const, x, y = node
        m = self.maps[const]
        ts = self.tilesets[m.tileset]
        here = self.terrain(node=node)
        if here is None:
            return

        for d, (dx, dy) in DELTA.items():
            nx_, ny_ = x + dx, y + dy
            inside = 0 <= nx_ < m.step_width and 0 <= ny_ < m.step_height

            if not inside:
                conn = self._conns[const].get(d)
                if conn is not None:
                    dst = self._cross(
                        connection=conn,
                        d=d,
                        x=x,
                        y=y,
                    )
                    if self.terrain(node=dst) is not None:
                        yield Edge(
                            dst=dst,
                            kind="connection",
                            direction=d,
                            requires=self._req(here, self.terrain(node=dst)),
                        )
                continue

            dst: Node = (const, nx_, ny_)
            there = self.terrain(node=dst)
            tile_here = self.collision_tile(node=node)

            if there is None:
                # solid, but maybe a ledge!
                jump = self._ledge(
                    tileset=ts,
                    direction=d,
                    standing=tile_here,
                    ledge_node=dst,
                )
                if jump is not None:
                    yield Edge(
                        dst=jump,
                        kind="ledge",
                        direction=d,
                        cost=1.0,
                    )

            if self._pair_blocked(
                tileset=ts,
                terrain=here,
                a=tile_here,
                b=self.collision_tile(node=dst),
            ):
                continue

            yield Edge(
                dst=dst,
                kind="walk",
                direction=d,
                requires=self._req(here, there),
            )

        yield from self._warps_out.get(node, ())
