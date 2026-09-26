"""Functions for exectuing navigation."""

from pyboy import PyBoy

DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WALK_HOLD_FRAMES = 12
WALK_SETTLE_FRAMES = 8
MAP_TRANSITION_SETTLE_FRAMES = 60


def walk_to(
    pyboy: PyBoy,
    syms: dict[str, int],
    x: int,
    y: int,
    max_steps: int = 150,
) -> None:
    """Walk to a point."""
    pass


def goto(waypoint: str):
    """Go to a waypoint."""
    pass
