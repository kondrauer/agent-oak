"""Server for the Pokemon MCP."""

from threading import Lock

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pyboy import PyBoy

from agent_oak.pokemon_mcp.emulator import grab_screen_png
from agent_oak.pokemon_mcp.mappings import Button
from agent_oak.pokemon_mcp.memory import read_badges, read_location, read_party
from agent_oak.pokemon_mcp.models import ObtainedBadges, PlayerLocation, Pokemon


def build_server(
    pyboy: PyBoy,
    symbols: dict[str, int],
    mem_lock: Lock,
) -> FastMCP:
    """Build the MCP server with the given emulator and symbols.

    Args:
        pyboy: The emulator instance to read from.
        symbols: The symbol table mapping names to addresses.
        mem_lock: A lock to synchronize access to the emulator's memory.
    Returns:
        An instance of FastMCP with the defined tools.
    """
    mcp = FastMCP(
        name="agent-oak",
    )

    @mcp.tool()
    def get_party() -> list[Pokemon]:
        """Get the player's party from the emulator.

        Returns:
            A list of Pokemon representing the player's party.
        """
        with mem_lock:
            return read_party(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def get_location() -> PlayerLocation:
        """Get the player's location from the emulator.

        Returns:
            A PlayerLocation object representing the player's location.
        """
        with mem_lock:
            return read_location(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def get_badges() -> ObtainedBadges:
        """Get the player's obtained badges from the emulator.

        Returns:
            An ObtainedBadges object representing the player's obtained badges.
        """
        with mem_lock:
            return read_badges(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def press_button(
        button: Button,
        hold_frames: int = 1,
    ) -> str:
        """Press a button on the emulator.

        Args:
            button: The name of the button to press
                (e.g., Button.A, Button.B, Button.UP, Button.DOWN).
            hold_frames: The number of frames to hold the button down (default is 1).
        Returns:
            A string indicating which button was pressed and for how many frames.
        """
        pyboy.button(
            button.value,
            delay=hold_frames,
        )
        return f"Pressed {button.name} for {hold_frames} frames"

    @mcp.tool()
    def advance_frames(frames: int) -> str:
        """Advance the emulator by a given number of frames.

        Args:
            frames: The number of frames to advance.
        Returns:
            A string indicating how many frames were advanced.
        """
        with mem_lock:
            for _ in range(frames):
                if not pyboy.tick():
                    break

        return f"Advanced {frames} frames"

    @mcp.tool()
    def get_screenshot(scale: int = 3) -> Image | None:
        """Take a screenshot of the emulator's current state.

        Args:
            scale: The scale factor to apply to the screenshot (default is 3).
        Returns:
            An Image object representing the emulator's screen,
                or None if the screenshot could not be taken.
        """
        with mem_lock:
            png = grab_screen_png(
                pyboy=pyboy,
                scale=scale,
            )
            if png is not None:
                return Image(
                    data=png,
                    format="PNG",
                )

    return mcp
