"""Emulator state module."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Lock

from pyboy import PyBoy
from pyboy.utils import WindowEvent


def create_emulator(rom_path: str) -> PyBoy:
    """Create a new emulator instance and run on background thread."""
    pyboy = PyBoy(
        rom_path,
        scale=1,
        debug=False,
        sound_emulated=True,
    )

    return pyboy


@contextmanager
def running(pyboy: PyBoy, mem_lock: Lock) -> Iterator[None]:
    """Let a paused emulator advance only for the duration of the block.

    In agent mode the emulator stays paused between tool calls, so the game
    does not drift while the LLM is thinking. If it is already running
    (manual mode, or unpaused with P), this only takes the lock.

    Args:
        pyboy: The emulator instance.
        mem_lock: A lock to synchronize access to the emulator's memory.
    """
    with mem_lock:
        was_paused = pyboy.paused
        if was_paused:
            # applied at the start of the next tick
            pyboy.send_input(WindowEvent.UNPAUSE)
        try:
            yield
        finally:
            if was_paused:
                pyboy.send_input(WindowEvent.PAUSE)
                # applies the pause without advancing a frame
                pyboy.tick()


def load_symbols(path: Path) -> dict[str, int]:
    """Load symbols from a file.

    Args:
        path: The path to the symbols file.
    Returns:
        A dictionary mapping symbol names to addresses.
    """
    syms = {}
    pat = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)")
    with path.open() as f:
        for line in f:
            m = pat.match(line)
            if m:
                bank, addr, name = m.groups()
                syms[name] = int(addr, 16)
    return syms


def grab_screen_png(pyboy: PyBoy, scale: int = 3) -> bytes | None:
    """Grab a screenshot of the emulator's current state as a PNG.

    Args:
        pyboy: The emulator instance to grab from.
        scale: The scale factor for the screenshot.
    Returns:
        A PNG image as bytes representing the emulator's screen.
    """
    if img := pyboy.screen.image:
        img = img.convert("RGB")
        if scale != 1:
            img = img.resize(
                size=(img.width * scale, img.height * scale),
                resample=0,
            )
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
