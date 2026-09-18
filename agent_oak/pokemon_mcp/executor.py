"""High level functions for an LLM to execute."""

from pyboy import PyBoy

from agent_oak.pokemon_mcp.memory import decode_text, read_dialogue_text, read_location

CURSOR_TILE = 0xED
DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WALK_HOLD_FRAMES = 12
WALK_SETTLE_FRAMES = 8
MAP_TRANSITION_SETTLE_FRAMES = 60
WY_HIDDEN = 0x90  # hWY value when no textbox/menu window is being drawn


def _is_dialogue_open(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if a dialogue box or menu window is currently open.

    Reads hWY, the shadow copy of the window Y-position register, instead
    of decoding wTileMap: the tilemap buffer can retain stale text bytes
    from an earlier, now-closed dialogue, which would otherwise be
    misread as an open textbox. hWY sits at WY_HIDDEN whenever the window
    layer is pushed off-screen, and at a lower value whenever a
    dialogue/menu window is actually being drawn.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a dialogue/menu box is open, False otherwise.
    """
    return pyboy.memory[syms["hWY"]] != WY_HIDDEN


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


def _in_battle(
    pyboy: PyBoy,
    syms: dict[str, int],
) -> bool:
    """Check if the player is currently in a battle.

    Args:
        pyboy: The PyBoy instance to read memory from.
        syms: A dictionary of constant names to their values.
    Returns:
        True if a battle is in progress, False otherwise.
    """
    return pyboy.memory[syms["wIsInBattle"]] != 0


def walk_to(
    pyboy: PyBoy,
    syms: dict[str, int],
    x: int,
    y: int,
    max_steps: int = 150,
) -> dict[str, object]:
    """Walk toward (x, y) on the current map, one tile at a time.

    There is no vendored collision/warp data for the ROM, so this moves
    greedily toward the target and detects walls by checking whether the
    player's coordinates actually changed after a button press ("bump
    detection"), backing off directions that turned out to be blocked from
    a given tile. It stops as soon as the map changes (e.g. stairs or a
    door were used), the target tile is reached, a battle or dialogue
    interrupts, or no direction makes progress.

    Args:
        pyboy: The PyBoy instance to read memory from and send input to.
        syms: A dictionary of constant names to their values.
        x: The target x coordinate on the current map.
        y: The target y coordinate on the current map.
        max_steps: The maximum number of tile-moves to attempt.
    Returns:
        A dictionary containing the status
            (arrived/map_changed/interupt/stuck/timeout) and final location.
    """
    start_map = read_location(pyboy=pyboy, syms=syms).map_id
    blocked: set[tuple[int, int, str]] = set()

    for _ in range(max_steps):
        loc = read_location(pyboy=pyboy, syms=syms)

        if loc.map_id != start_map:
            # The map/coordinate bytes update in separate writes during the
            # transition, so let it fully settle before reporting location.
            for _ in range(MAP_TRANSITION_SETTLE_FRAMES):
                pyboy.tick()
            loc = read_location(pyboy=pyboy, syms=syms)
            return {"status": "map_changed", "location": loc.model_dump()}
        if loc.x == x and loc.y == y:
            return {"status": "arrived", "location": loc.model_dump()}
        if _in_battle(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "battle",
                "location": loc.model_dump(),
            }
        if _is_dialogue_open(pyboy=pyboy, syms=syms):
            return {
                "status": "interupt",
                "reason": "dialogue",
                "location": loc.model_dump(),
            }

        dx, dy = x - loc.x, y - loc.y
        toward = []
        if dx > 0:
            toward.append("right")
        elif dx < 0:
            toward.append("left")
        if dy > 0:
            toward.append("down")
        elif dy < 0:
            toward.append("up")
        if abs(dy) > abs(dx):
            toward.reverse()
        # Prefer sideways detours over backtracking away from the target,
        # e.g. don't retreat "up" just because "down" is blocked.
        avoid = {OPPOSITE[d] for d in toward}
        sideways = [d for d in DIRECTIONS if d not in toward and d not in avoid]
        backtrack = [d for d in DIRECTIONS if d not in toward and d in avoid]
        order = toward + sideways + backtrack
        unblocked = [d for d in order if (loc.x, loc.y, d) not in blocked]

        moved = False
        for direction in unblocked or order:
            pyboy.button(direction, delay=WALK_HOLD_FRAMES)
            for _ in range(WALK_HOLD_FRAMES + WALK_SETTLE_FRAMES):
                pyboy.tick()
            new_loc = read_location(pyboy=pyboy, syms=syms)
            if (new_loc.map_id, new_loc.x, new_loc.y) != (loc.map_id, loc.x, loc.y):
                moved = True
                break
            blocked.add((loc.x, loc.y, direction))

        if not moved:
            return {"status": "stuck", "location": loc.model_dump()}

    return {
        "status": "timeout",
        "location": read_location(pyboy=pyboy, syms=syms).model_dump(),
    }


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
