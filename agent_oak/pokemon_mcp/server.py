"""Server for the Pokemon MCP."""

from threading import Lock

from fastmcp import FastMCP
from pyboy import PyBoy

from agent_oak.pokemon_mcp.memory import read_party
from agent_oak.pokemon_mcp.models import Pokemon


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

        Args:
            emulator: The emulator instance to read from.
            symbols: The symbol table mapping names to addresses.
        Returns:
            A list of Pokemon representing the player's party.
        """
        with mem_lock:
            return read_party(pyboy=pyboy, syms=symbols)

    return mcp
