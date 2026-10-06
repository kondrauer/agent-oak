"""Hint texts for a milestone, generated from its YAML data by tier."""

from agent_oak.objectives.milestones import Milestone
from agent_oak.objectives.routing import Route

MAX_TIER = 3


def where(milestone: Milestone) -> str:
    """Where the milestone happens, e.g. "CERULEAN_GYM, CERULEANGYM_MISTY at (4, 2)"."""
    if milestone.map is None:
        return "anywhere, it is done from the menu"
    target = milestone.target
    if target is None:
        return milestone.map
    if target.kind == "npc":
        return f"{milestone.map}, {target.name} at ({target.x}, {target.y})"
    if target.kind == "warp":
        return f"{milestone.map}, the warp to {target.name} at ({target.x}, {target.y})"
    return f"{milestone.map}, tile ({target.x}, {target.y})"


def hint_text(milestone: Milestone, tier: int, route: Route | None = None) -> str:
    """Write the hint for 'milestone' at 'tier', more specific the higher.

    0: the goal's label, 1: its blurb, 2: plus where, 3: plus the path from
    the player's position ('route').
    """
    if tier <= 0:
        return milestone.label
    lines = [milestone.blurb]
    if tier >= 2:
        lines.append(f"Where: {where(milestone)}")
    if tier >= 3 and route is not None:
        if route.status in ("route", "here"):
            lines.append(f"Path: {route.summary}")
        elif route.status == "no_path":
            lines.append("Path: none from here with your current abilities")
    return "\n".join(lines)
