"""Emulator state module."""

from pyboy import PyBoy

pyboy = PyBoy("pokemon-red.gb", scale=1, debug=False)

pyboy.set_emulation_speed(1)

while True:
    pyboy.tick(render=True)
