"""Application entry point."""

from pathlib import Path
from threading import Lock, Thread

from agent_oak.pokemon_mcp.emulator import create_emulator, load_symbols
from agent_oak.pokemon_mcp.server import build_server

ROM_PATH = "pokemon-red.gb"
SYM_PATH = "pokered.sym"

if __name__ == "__main__":
    syms = load_symbols(path=Path(SYM_PATH))
    pyboy = create_emulator(rom_path=ROM_PATH)
    mem_lock = Lock()

    mcp = build_server(
        pyboy=pyboy,
        symbols=syms,
        mem_lock=mem_lock,
    )

    Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=8765),
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
