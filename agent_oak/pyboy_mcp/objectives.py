"""Objective tools and the status line on every action tool."""

import asyncio

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from agent_oak.objectives.tracker import (
    HintResult,
    ObjectiveReport,
    ObjectiveTracker,
    RouteResult,
)

ACTION_TAG = "action"
"""Tag of the tools that advance the game, they get the status line."""


class ObjectiveMiddleware(Middleware):
    """Add the objective status line to every action tool's result.

    Milestones completed by the action come first ("✓ Completed: ..."), the
    status line last. Results with structured content also get both under
    'objective', for clients that only read that.
    """

    def __init__(self, tracker: ObjectiveTracker) -> None:
        """Report the progress 'tracker' sees."""
        self.tracker = tracker

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Run the tool, then evaluate the objectives if it was an action."""
        result = await call_next(context)
        server = context.fastmcp_context.fastmcp if context.fastmcp_context else None
        tool = await server.get_tool(context.message.name) if server else None
        if tool is None or ACTION_TAG not in tool.tags or result.is_error:
            return result

        # reads RAM under mem_lock, keep it off the event loop
        observation = await asyncio.to_thread(self.tracker.observe)
        completed = observation.completed_line()
        lines = [completed, observation.status] if completed else [observation.status]

        before = [mt.TextContent(type="text", text=completed)] if completed else []
        after = [mt.TextContent(type="text", text=observation.status)]
        structured = result.structured_content
        if isinstance(structured, dict):
            structured = {**structured, "objective": "\n".join(lines)}
        return ToolResult(
            content=before + list(result.content) + after,
            structured_content=structured,
            meta=result.meta,
        )


def add_objective_tools(mcp: FastMCP, tracker: ObjectiveTracker) -> None:
    """Register get_objective, get_hint and route_to_objective on 'mcp'.

    Also installs the middleware that adds the status line to action tools.
    """
    mcp.add_middleware(ObjectiveMiddleware(tracker=tracker))

    @mcp.tool()
    def get_objective() -> ObjectiveReport:
        """Get the current story goal, checked against the game's flags.

        Returns:
            The current goal and the other open ones with what to do and
                where, the hint at the current tier, readiness notes (e.g.
                the gym leader's strongest Pokemon), progress, party levels
                and usable field moves.
        """
        return tracker.report()

    @mcp.tool()
    def get_hint() -> HintResult:
        """Get a more specific hint for the current goal.

        Each call raises the hint tier by one: 1 says what to do, 2 adds
        where, 3 adds the path from the player's position. The tier goes
        back to 0 when the goal changes.

        Returns:
            The goal, the new tier and its hint.
        """
        return tracker.bump_hint()

    @mcp.tool(tags={ACTION_TAG})
    def route_to_objective(execute: bool = False) -> RouteResult:
        """Plan the path to the current goal, and walk it with execute.

        Ends next to the goal's NPC (talk with talk_to_tool), on its tile or
        anywhere on its map. Walking stops at battles and text boxes like
        goto_map does, call again to continue.

        Args:
            execute: Walk the path instead of only planning it.
        Returns:
            The goal's target, the steps and maps on the way, or why there
                is no path, plus how the walk went when executed.
        """
        return tracker.route(execute=execute)
