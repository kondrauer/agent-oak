"""The objective tools and the status line, over MCP against the real save."""

from collections.abc import Callable, Iterator
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
from agent_oak.objectives.progress import HintPolicy
from agent_oak.objectives.tracker import ObjectiveTracker
from agent_oak.parser.maps import parse_maps, parse_tilesets
from agent_oak.pyboy_mcp.emulator import load_symbols
from agent_oak.pyboy_mcp.server import build_server

Server = tuple[FastMCP, PyBoy, dict[str, int], ObjectiveTracker]


@pytest.fixture
def make_server(constants: dict[str, Any]) -> Iterator[Callable[..., Server]]:
    """Build full MCP servers on the save after Brock, stopped afterwards."""
    if not (ROM.exists() and SAVE_AFTER_BROCK.exists()):
        pytest.skip("needs pokemon-red.gb and pokemon-red.gb.state in the repo root")
    syms = load_symbols(Path("pokered.sym"))
    maps_by_name, maps_by_id = parse_maps()
    world = World(maps=maps_by_name, tilesets=parse_tilesets()[0])
    objectives = load_objectives(maps=maps_by_name, constants=constants)
    emulators: list[PyBoy] = []

    def make(
        policy: HintPolicy | None = None, state_path: Path | None = None
    ) -> Server:
        pyboy = PyBoy(str(ROM), window="null", sound_emulated=False)
        emulators.append(pyboy)
        with SAVE_AFTER_BROCK.open("rb") as f:
            pyboy.load_state(f)
        mem_lock = Lock()
        tracker = ObjectiveTracker(
            evaluator=Evaluator(
                objectives=objectives, num_events=constants["num_events"]
            ),
            world=world,
            pyboy=pyboy,
            syms=syms,
            maps_by_id=maps_by_id,
            mem_lock=mem_lock,
            policy=policy,
            state_path=state_path,
        )
        mcp = build_server(
            pyboy=pyboy,
            symbols=syms,
            maps_by_id=maps_by_id,
            world=world,
            mem_lock=mem_lock,
            tracker=tracker,
        )
        return mcp, pyboy, syms, tracker

    yield make
    for pyboy in emulators:
        pyboy.stop(save=False)


@pytest.fixture
def server(make_server: Callable[..., Server]) -> Server:
    """Build a server with the default policy."""
    return make_server()


def _texts(result: Any) -> list[str]:
    return [c.text for c in result.content]


async def test_status_line_on_actions_only(server) -> None:
    """Action tools end with the status line, reading tools are unchanged."""
    mcp, *_ = server
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
    mcp, pyboy, syms, _ = server
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
    mcp, *_ = server
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


def _set_event(pyboy: PyBoy, syms: dict[str, int], index: int) -> None:
    pyboy.memory[syms["wEventFlags"] + index // 8] |= 1 << (index % 8)


async def test_stall_raises_the_hint(make_server, constants) -> None:
    """Standing still raises the tier up to max_auto_tier, a new goal resets it."""
    mcp, pyboy, syms, tracker = make_server(
        policy=HintPolicy(stall_calls=2, max_auto_tier=2)
    )
    async with Client(mcp) as client:
        calls = [
            _texts(await client.call_tool("press_button", {"button": "b"}))
            for _ in range(7)
        ]
        _set_event(
            pyboy, syms, constants["events"]["EVENT_BEAT_MT_MOON_EXIT_SUPER_NERD"]
        )
        after_goal = _texts(await client.call_tool("press_button", {"button": "b"}))

    notices = [i for i, texts in enumerate(calls) if texts[0].startswith("💡")]
    # the first call visits the tile, then every second call stalls
    assert notices == [2, 4, 6]
    assert calls[2][0].startswith("💡 No progress in the last 2 actions. Hint: Take")
    assert "Where: MT_MOON_B2F" in calls[4][0]
    assert calls[6][-1].endswith("hint 2]")  # capped at max_auto_tier
    assert after_goal[0] == "✓ Completed: Get through Mt. Moon"
    assert after_goal[-1].endswith("hint 0]")


async def test_state_survives_a_restart(make_server, tmp_path) -> None:
    """Tier and visited tiles are saved and loaded again."""
    path = tmp_path / "objectives.json"
    mcp, *_, tracker = make_server(state_path=path)
    async with Client(mcp) as client:
        await client.call_tool("press_button", {"button": "b"})
        await client.call_tool("get_hint", {})

    assert path.exists()
    restored = make_server(state_path=path)[3]
    assert restored.hint_tier == 1
    assert restored.progress.visited == tracker.progress.visited
    assert restored.progress.visited  # the tile of the first press


async def test_hints_off(make_server) -> None:
    """Off shows only the goal's name, no hints, no routing."""
    mcp, *_ = make_server(policy=HintPolicy(mode="off"))
    async with Client(mcp) as client:
        status = _texts(await client.call_tool("press_button", {"button": "b"}))[-1]
        objective = (await client.call_tool("get_objective", {})).structured_content
        hint = (await client.call_tool("get_hint", {})).structured_content
        route = (await client.call_tool("route_to_objective", {})).structured_content

    assert status == "[Goal: Get through Mt. Moon | Party Lv 15]"
    assert (
        objective["goal"]["blurb"] == ""
        and objective["hint"] == objective["goal"]["label"]
    )
    assert hint["tier"] == 0 and hint["note"].startswith("Hints are off")
    assert route["status"] == "disabled"
