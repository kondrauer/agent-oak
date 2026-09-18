"""High level functions for an LLM to execute."""

from pyboy import PyBoy

from agent_oak.pokemon_mcp.memory import decode_text, read_dialogue_text

CURSOR_TILE = 0xED


def _is_dialogue_open(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if a dialogue box is currently open.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a dialogue box is open, False otherwise.
    """
    base = syms["wTileMap"]
    for row in (13, 14, 15, 16):
        row_bytes = bytes(pyboy.memory[base + row * 20 : base + row * 20 + 20])
        if decode_text(row_bytes).strip():
            return True
    return False


def _yes_no_prompt_detected(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if a yes/no prompt is currently open.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a yes/no prompt is open, False otherwise.
    """
    base = syms["wTileMap"]
    grid = bytes(pyboy.memory[base : base + 20 * 18])
    text = decode_text(grid)
    return "YES" in text and "NO" in text and CURSOR_TILE in grid


def check_for_interupt(syms: dict[str, int], check_for_battle: bool) -> bool:
    """Check for an interupt signal from the user."""
    return False


def walk_to(map_id: int, x: int, y: int):
    """Walk to a location on the map."""
    pass


def goto(waypoint: str):
    """Go to a waypoint."""
    pass


def advance_dialogue(
    pyboy: PyBoy,
    syms: dict[str, int],
    timeout_frames: int = 600,
) -> dict[str, str | bool]:
    """Advances a dialogue until exhausted or yes/no question is reached.

    If in battle stops when battle actions are available.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        timeout_frames: The maximum number of frames to wait before timing out.
    Returns:
        A dictionary containing the status and collected text.
    """
    collected, last_text = [], ""
    idle = 0
    for frame in range(timeout_frames):
        if interupt_reasons := check_for_interupt(
            syms,
            check_for_battle=True,
        ):
            return {
                "status": "interupt",
                "reason": interupt_reasons,
                "text": "\n".join(collected),
            }

        if frame % 16 == 0:  # press A periodically
            pyboy.button("a")
        pyboy.tick()  # if your loop doesn't drive ticks here, drop this
        if _yes_no_prompt_detected(
            pyboy=pyboy,
            syms=syms,
        ):
            return {
                "status": "prompt",
                "kind": "yes_no",
                "text": "\n".join(collected),
                "selected": pyboy.memory[syms["wCurrentMenuItem"]],
            }
        text = read_dialogue_text(
            pyboy=pyboy,
            syms=syms,
        ).text
        in_dialogue = _is_dialogue_open(
            pyboy=pyboy,
            syms=syms,
        )
        if text and text != last_text:
            collected.append(text)
            last_text = text
            idle = 0
        else:
            idle += 1
        if not in_dialogue and idle > 30:
            return {
                "status": "done",
                "text": "\n".join(collected),
            }
    return {
        "status": "timeout",
        "text": "\n".join(collected),
    }


def talk_to_npc(npc_id: int):
    """Talk to an NPC."""
    pass


def battle_use_move(move_id: int):
    """Use a move in battle."""
    pass


def battle_switch(pokemon_id: int):
    """Switch to a different Pokemon in battle."""
    pass


def battle_run():
    """Attempt to run from battle."""
    pass


def wait_until(condition: str):
    """Wait until a certain condition is met."""
    pass
