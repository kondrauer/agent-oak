"""The objective tools and the status line, over MCP against the real save."""

from collections.abc import Iterator
from pathlib import Path
from threading import Lock
from typing import Any

import pytest
from conftest import ROM, SAVE_AFTER_BROCK
from fastmcp import Client, FastMCP
from pyboy import PyBoy

from agent_oak.executor.models import World
from agent_oak.objectives.evaluator import Evaluator
from agent_oak.objectives.milestones import load_objectives
from agent_oak.objectives.tracker import ObjectiveTracker
from agent_oak.parser.maps import parse_maps, parse_tilesets
from agent_oak.pyboy_mcp.emulator import load_symbols
from agent_oak.pyboy_mcp.server import build_server


@pytest.fixture
def server(constants: dict[str, Any]) -> Iterator[tuple[FastMCP, PyBoy, dict]]:
    """Build the full MCP server on the save after Brock."""
    if not (ROM.exists() and SAVE_AFTER_BROCK.exists()):
        pytest.skip("needs pokemon-red.gb and pokemon-red.gb.state in the repo root")
    syms = load_symbols(Path("pokered.sym"))
    maps_by_name, maps_by_id = parse_maps()
    world = World(maps=maps_by_name, tilesets=parse_tilesets()[0])
    pyboy = PyBoy(str(ROM), window="null", sound_emulated=False)
    with SAVE_AFTER_BROCK.open("rb") as f:
        pyboy.load_state(f)
    mem_lock = Lock()
    tracker = ObjectiveTracker(
        evaluator=Evaluator(
            objectives=load_objectives(maps=maps_by_name, constants=constants),
            num_events=constants["num_events"],
        ),
        world=world,
        pyboy=pyboy,
        syms=syms,
        maps_by_id=maps_by_id,
        mem_lock=mem_lock,
    )
    mcp = build_server(
        pyboy=pyboy,
        symbols=syms,
        maps_by_id=maps_by_id,
        world=world,
        mem_lock=mem_lock,
        tracker=tracker,
    )
    yield mcp, pyboy, syms
    pyboy.stop(save=False)


def _texts(result: Any) -> list[str]:
    return [c.text for c in result.content]


async def test_status_line_on_actions_only(server) -> None:
    """Action tools end with the status line, reading tools are unchanged."""
    mcp, _, _ = server
    async with Client(mcp) as client:
        pressed = await client.call_tool("press_button", {"button": "b"})
        party = await client.call_tool("get_party", {})

    status = _texts(pressed)[-1]
    assert status.startswith("[Goal: Get through Mt. Moon @ MT_MOON_B2F |")
    assert "Party Lv 15" in status and status.endswith("hint 0]")
    assert len(status) <= 150
    assert pressed.structured_content["objective"] == status
    assert not any(t.startswith("[Goal:") for t in _texts(party))


async def test_completed_milestone_is_reported(server, constants) -> None:
    """A milestone done since the last action gets a ✓ line, once."""
    mcp, pyboy, syms = server
    index = constants["events"]["EVENT_BEAT_MT_MOON_EXIT_SUPER_NERD"]
    async with Client(mcp) as client:
        await client.call_tool("press_button", {"button": "b"})
        pyboy.memory[syms["wEventFlags"] + index // 8] |= 1 << (index % 8)
        first = await client.call_tool("press_button", {"button": "b"})
        second = await client.call_tool("press_button", {"button": "b"})

    assert _texts(first)[0] == "✓ Completed: Get through Mt. Moon"
    assert _texts(first)[-1].startswith("[Goal: Reach Cerulean City")
    assert not _texts(second)[0].startswith("✓")


async def test_hint_tiers_and_route(server) -> None:
    """get_hint gets more specific up to the path, the route plans it."""
    mcp, _, _ = server
    async with Client(mcp) as client:
        objective = (await client.call_tool("get_objective", {})).structured_content
        hints = [
            (await client.call_tool("get_hint", {})).structured_content
            for _ in range(4)
        ]
        route = (await client.call_tool("route_to_objective", {})).structured_content
        pressed = await client.call_tool("press_button", {"button": "b"})

    assert objective["goal"]["id"] == "BEAT_MT_MOON_SUPER_NERD"
    assert objective["hint_tier"] == 0 and objective["done"] == 7
    assert [h["tier"] for h in hints] == [1, 2, 3, 3]
    assert "Where: MT_MOON_B2F, MTMOONB2F_SUPER_NERD at (12, 8)" in hints[1]["hint"]
    assert "Path: " in hints[2]["hint"] and "MT_MOON_1F" in hints[2]["hint"]
    assert hints[3]["note"] is not None
    assert route["status"] == "route"
    assert route["maps"][-3:] == ["MT_MOON_1F", "MT_MOON_B1F", "MT_MOON_B2F"]
    assert _texts(pressed)[-1].endswith("hint 3]")
