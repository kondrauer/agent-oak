"""Application entry point."""

import argparse
from pathlib import Path
from threading import Lock, Thread

from pyboy.utils import WindowEvent

from agent_oak.parser.maps import parse_maps
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
    args = parser.parse_args()

    syms = load_symbols(path=Path(SYM_PATH))
    _, maps_by_id = parse_maps()
    pyboy = create_emulator(rom_path=ROM_PATH)
    mem_lock = Lock()

    if not args.manual:
        # agent mode: the game only advances inside tool calls
        pyboy.send_input(WindowEvent.PAUSE)

    mcp = build_server(
        pyboy=pyboy,
        symbols=syms,
        maps_by_id=maps_by_id,
        mem_lock=mem_lock,
    )

    Thread(
        target=lambda: mcp.run(
            transport="http",
            host="127.0.0.1",
            port=8765,
        ),
        daemon=True,
    ).start()

    try:
        while True:
            with mem_lock:
                still_running = pyboy.tick()
            if not still_running:
                break
    finally:
        pyboy.stop()


if __name__ == "__main__":
    main()
