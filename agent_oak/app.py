"""Application entry point."""

import argparse
from pathlib import Path
from threading import Lock, Thread

from pyboy.utils import WindowEvent

from agent_oak.executor.models import Node, World
from agent_oak.executor.navigation import goto
from agent_oak.memory.read import read_location
from agent_oak.objectives.constants import load_constants_json
from agent_oak.objectives.evaluator import Evaluator
from agent_oak.objectives.milestones import load_objectives
from agent_oak.objectives.tracker import ObjectiveTracker
from agent_oak.parser.maps import parse_maps, parse_tilesets
from agent_oak.pyboy_mcp.emulator import create_emulator, load_symbols
from agent_oak.pyboy_mcp.server import build_server

ROM_PATH = "pokemon-red.gb"
SYM_PATH = "pokered.sym"


def main() -> None:
    """Start the emulator and serve the MCP server."""
    parser = argparse.ArgumentParser(description="Run the AgentOak MCP server.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="start unpaused so the game runs freely and can be played by hand "
        "(press P in the window to toggle pause at any time)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="show every frame at real speed, also while tools run (slower, "
        "tools otherwise skip ahead many frames at once)",
    )
    parser.add_argument(
        "--record",
        metavar="FILE",
        type=Path,
        help="record the gameplay to a video file (e.g. run.mp4, needs "
        "ffmpeg), paused time is left out, implies --realtime",
    )
    parser.add_argument(
        "--goto",
        metavar="MAP",
        help="debug: once in the overworld, walk to the first warp of MAP "
        "(e.g. OAKS_LAB) and print the map whenever the player moves",
    )
    args = parser.parse_args()

    syms = load_symbols(path=Path(SYM_PATH))
    maps_by_name, maps_by_id = parse_maps()
    tilesets_by_name, _ = parse_tilesets()
    world = World(
        maps=maps_by_name,
        tilesets=tilesets_by_name,
    )
    pyboy = create_emulator(
        rom_path=ROM_PATH,
        realtime=args.realtime,
        record_path=args.record,
    )
    mem_lock = Lock()
    constants = load_constants_json()
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

    if not args.manual:
        # agent mode: the game only advances inside tool calls
        pyboy.send_input(WindowEvent.PAUSE)

    mcp = build_server(
        pyboy=pyboy,
        symbols=syms,
        maps_by_id=maps_by_id,
        world=world,
        mem_lock=mem_lock,
        tracker=tracker,
    )

    Thread(
        target=lambda: mcp.run(
            transport="http",
            host="127.0.0.1",
            port=8765,
        ),
        daemon=True,
    ).start()

    goal: Node | None = None
    if args.goto:
        warp = maps_by_name[args.goto].warps[0]
        goal = (args.goto, warp.x, warp.y)
    last_node: Node | None = None

    try:
        while True:
            with mem_lock:
                still_running = pyboy.tick()

                if goal is not None:
                    try:
                        loc = read_location(
                            pyboy=pyboy,
                            syms=syms,
                            maps_by_id=maps_by_id,
                        )
                    except Exception:
                        # e.g. title screen, wCurMap not a valid map yet
                        loc = None

                    node = None if loc is None else (loc.map.const, loc.x, loc.y)
                    # only (re)plan when the player moved, not every frame
                    if node is not None and node != last_node:
                        last_node = node
                        status = goto(
                            pyboy=pyboy,
                            syms=syms,
                            maps_by_id=maps_by_id,
                            world=world,
                            goal=goal,
                        )
                        if status == "reached":
                            print(f"Reached {goal}")
                            goal = None
                        else:
                            print(f"goto stopped: {status}")
            if not still_running:
                break
    finally:
        pyboy.stop()


if __name__ == "__main__":
    main()
