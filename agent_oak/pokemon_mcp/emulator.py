"""Emulator state module."""

import re
from pathlib import Path

from pyboy import PyBoy


def create_emulator(rom_path: str) -> PyBoy:
    """Create a new emulator instance and run on background thread."""
    pyboy = PyBoy(
        rom_path,
        scale=1,
        debug=False,
        sound_emulated=True,
    )

    return pyboy


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
