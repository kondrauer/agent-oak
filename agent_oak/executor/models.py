"""Models for executor module."""

from typing import Iterator, Literal

from pydantic import BaseModel

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


class Edge(BaseModel):
    """Edge in the world class."""

    dst: Node
    kind: Literal["walk", "ledge", "connection", "warp"]
    direction: Direction | None = None
    requires: frozenset[str] = frozenset()
    cost: float = 1.0


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
        self._conns: dict[str, dict[Direction, Connection]] = {}
        self._index()

    def _index(self) -> None:
        for const, m in self.maps.items():
            self._conns[const] = {Direction(c.direction): c for c in m.connections}
            for i, w in enumerate(m.warps):
                if w.dest_map == "LAST_MAP":
                    continue
                dest = self.maps.get(w.dest_map)
                if dest is None:
                    print(f"Dest map {w.dest_map} not found for warp {w}")
                    continue
                dw = dest.warps[self._warp_index(w.dest_warp)]
                src: Node = (const, w.x, w.y)
                self._warps_out.setdefault(src, []).append(
                    Edge(
                        dst=(w.dest_map, dw.x, dw.y),
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
        return frozenset({"SURF"}) if "water" in (a, b) else frozenset()

    def in_bounds(self, node: Node) -> bool:
        """Check if a node is in bounds."""
        const, x, y = node
        m = self.maps.get(const)
        if m is None:
            return False

        return 0 <= x < m.step_width and 0 <= y < m.step_height

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
        """'land', 'water' or None if the step is solid."""
        if not self.in_bounds(node):
            return None

        ts = self.tilesets[self.maps[node[0]].tileset]
        t = self.collision_tile(node=node)
        if t in ts.collision:
            return "land"
        if t in ts.water:
            return "water"
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
