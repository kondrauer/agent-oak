"""Functions for driving dialogues."""

from pyboy import PyBoy

from agent_oak.memory.read import (
    read_dialogue_text,
    read_is_dialogue_open,
    read_yes_no_prompt_detected,
)


def check_for_interupt(
    syms: dict[str, int],
    check_for_battle: bool,
) -> bool:
    """Check for an interupt signal from the user."""
    return False


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
        if read_yes_no_prompt_detected(
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
        in_dialogue = read_is_dialogue_open(
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
