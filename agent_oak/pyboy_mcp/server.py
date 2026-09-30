"""Server for the Pokemon MCP."""

from threading import Lock

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pyboy import PyBoy

from agent_oak.executor.battle import battle_run, battle_switch, battle_use_move
from agent_oak.executor.dialogue import advance_dialogue, select_option, talk_to
from agent_oak.executor.models import TalkResult, World
from agent_oak.executor.navigation import goto
from agent_oak.memory.models import (
    BagItems,
    BattleState,
    BattleTurn,
    Button,
    DialogueResult,
    MapObjects,
    ObtainedBadges,
    PlayerLocation,
    Pokemon,
    TextState,
)
from agent_oak.memory.read import (
    read_badges,
    read_bag,
    read_battle_state,
    read_location,
    read_map_objects,
    read_party,
    read_text_state,
)
from agent_oak.memory.render_map import render_current_map
from agent_oak.parser.maps import search_maps
from agent_oak.parser.models import GameMap, MapInfo
from agent_oak.pyboy_mcp.emulator import grab_screen_png, running


def build_server(
    pyboy: PyBoy,
    symbols: dict[str, int],
    maps_by_id: dict[int, GameMap],
    world: World,
    mem_lock: Lock,
) -> FastMCP:
    """Build the MCP server with the given emulator and symbols.

    Args:
        pyboy: The emulator instance to read from.
        symbols: The symbol table mapping names to addresses.
        maps_by_id: Parsed game maps keyed by map id.
        world: The world model used for pathfinding, its maps are keyed by const.
        mem_lock: A lock to synchronize access to the emulator's memory.
    Returns:
        An instance of FastMCP with the defined tools.
    """
    mcp = FastMCP(
        name="agent-oak",
    )

    @mcp.tool()
    def advance_dialogue_tool(timeout_frames: int = 1800) -> DialogueResult:
        """Read and click through text until it ends or a choice is needed.

        Only presses A on finished pages, never inside menus. Stops at yes/no
        prompts and other menus (answer with select_option_tool) and at the
        battle menu (FIGHT / PKMN / ITEM / RUN). Waits through scripted scenes
        like an NPC walking the player somewhere.

        Args:
            timeout_frames: Frame budget, call again after a timeout to go on.
        Returns:
            'status' (done, menu, battle_menu or timeout), every line shown
                in order, and the menu waiting for a choice, if any.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return advance_dialogue(
                pyboy=pyboy,
                syms=symbols,
                timeout_frames=timeout_frames,
            )

    @mcp.tool()
    def select_option_tool(index: int, timeout_frames: int = 1800) -> DialogueResult:
        """Choose an option of the open menu and read what follows.

        Works for any menu the dialogue tools report: yes/no prompts,
        Pokecenter, start menu, and in battle the FIGHT / PKMN / ITEM / RUN
        menu, the move list and the party list. For battles prefer use_move,
        switch_pokemon and run_from_battle, they pick by name.

        Args:
            index: Index into the menu's options, e.g. 0 for YES, 1 for NO.
            timeout_frames: Frame budget for the dialogue after the choice.
        Returns:
            The dialogue after the choice, like advance_dialogue_tool.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return select_option(
                pyboy=pyboy,
                syms=symbols,
                index=index,
                timeout_frames=timeout_frames,
            )

    @mcp.tool()
    def talk_to_tool(x: int, y: int) -> TalkResult:
        """Walk next to an NPC, sign or object on the current map and talk to it.

        Walks around the target to a free tile next to it (or across a
        counter, like the Pokecenter nurse), faces it, presses A and reads
        the dialogue. Follows an NPC that walks away once.

        Args:
            x: Target x in steps on the current map (see get_npcs).
            y: Target y in steps on the current map (see get_npcs).
        Returns:
            'walk' (reached, or why the target could not be reached, e.g.
                in_battle) and the dialogue if it was started.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return talk_to(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
                world=world,
                x=x,
                y=y,
            )

    @mcp.tool()
    def get_npcs() -> MapObjects:
        """List the NPCs and signs on the current map.

        Returns:
            Visible NPCs with their live position, facing and static data
                (sprite, text, trainer or item), and the map's signs.
        """
        with mem_lock:
            return read_map_objects(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
            )

    @mcp.tool()
    def find_maps(query: str) -> list[MapInfo]:
        """Search all maps by a substring of their name.

        Matching ignores case, spaces, underscores and apostrophes, so
        "oak's lab" finds OAKS_LAB and "viridian" finds every Viridian map.

        Args:
            query: Part of the map name, e.g. "pewter gym" or "ROUTE_2".
        Returns:
            The matching maps with their warps, connections, objects and signs.
                Use a map's 'const' as target for goto_map. Warp and object
                coordinates are steps, width and height are blocks (2x2 steps).
        """
        return [m.info() for m in search_maps(maps_by_name=world.maps, query=query)]

    @mcp.tool()
    def goto_map(
        map_const: str,
        x: int | None = None,
        y: int | None = None,
    ) -> dict[str, object]:
        """Walk to a map, or to a step coordinate on a map.

        Plans a path over tiles, ledges, warps and map connections, walks it
        and replans around NPCs that get in the way. Stops early when the
        walk is interrupted (wild battle, text box), handle that and call
        again to continue.

        Args:
            map_const: Target map constant, e.g. OAKS_LAB (see find_maps).
            x: Target x in steps. Omit x and y to go to the map's first warp.
            y: Target y in steps. Omit x and y to go to the map's first warp.
        Returns:
            Whether the goal was reached, the goal, where the player ended up
                and 'status': "reached", "in_battle", "dialogue_open",
                "no_path" (goal unreachable from here) or "gave_up" (kept
                getting blocked, e.g. by moving NPCs).
        """
        target = world.maps.get(map_const)
        if target is None or map_const == "LAST_MAP":
            return {"reached": False, "error": f"Unknown map {map_const}"}

        if x is None and y is None:
            if not target.warps:
                return {
                    "reached": False,
                    "error": f"{map_const} has no warps, pass x and y",
                }
            x, y = target.warps[0].x, target.warps[0].y
        elif x is None or y is None:
            return {"reached": False, "error": "Pass both x and y, or neither"}

        goal = (map_const, x, y)
        # some warps sit on solid tiles, they are still reachable through
        # the warp edge that lands on them
        is_warp = any((w.x, w.y) == (x, y) for w in target.warps)
        if not is_warp and world.terrain(node=goal) is None:
            return {
                "reached": False,
                "error": f"{goal} is out of bounds or not walkable",
            }

        with running(pyboy=pyboy, mem_lock=mem_lock):
            status = goto(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
                world=world,
                goal=goal,
            )
            loc = read_location(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
            )

        return {
            "reached": status == "reached",
            "status": status,
            "goal": {"map": map_const, "x": x, "y": y},
            "location": {"map": loc.map.const, "x": loc.x, "y": loc.y},
        }

    @mcp.tool()
    def get_map() -> str:
        """Render the current map as an ASCII grid in step coordinates.

        Use it to pick x, y targets on the current map for goto_map. Columns
        are x, rows are y. The legend and the warp targets are printed above
        the grid.

        Returns:
            The rendered map.
        """
        with mem_lock:
            return render_current_map(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
                maps_by_name=world.maps,
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
                maps_by_id=maps_by_id,
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
    def get_bag() -> BagItems:
        """Get the player's bag contents from the emulator.

        Returns:
            A BagItems object representing the player's bag contents.
        """
        with mem_lock:
            return read_bag(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def use_move(move: str) -> BattleTurn:
        """Use a move of the active Pokemon, from the battle menu.

        Args:
            move: Move name as in get_battle_state, e.g. "TACKLE".
        Returns:
            The turn's text up to the next decision: status battle_menu when
                it is your turn again, menu for prompts (e.g. learn a move,
                pick the next Pokemon), done or timeout when the battle
                ended (call advance_dialogue_tool on timeout). Plus the
                battle state after the turn.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return battle_use_move(
                pyboy=pyboy,
                syms=symbols,
                move=move,
            )

    @mcp.tool()
    def switch_pokemon(pokemon: str) -> BattleTurn:
        """Send out another party Pokemon.

        Works from the battle menu and when the game asks for the next
        Pokemon after one fainted.

        Args:
            pokemon: Nickname of the party Pokemon, e.g. "PIKACHU".
        Returns:
            The turn's text up to the next decision and the battle state.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return battle_switch(
                pyboy=pyboy,
                syms=symbols,
                pokemon=pokemon,
            )

    @mcp.tool()
    def run_from_battle() -> BattleTurn:
        """Try to run away, only possible in wild battles.

        Returns:
            The text (got away, or failed and the enemy's turn) and the
                battle state.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return battle_run(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def get_battle_state() -> BattleState:
        """Get the current battle state from the emulator.

        Returns:
            A BattleState object representing the current battle state.
        """
        with mem_lock:
            return read_battle_state(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def get_dialogue() -> TextState:
        """Get what the text box currently shows, without pressing anything.

        Returns:
            Whether a text box is open, its lines, whether the game waits
                for A and the menu waiting for a choice, if any.
        """
        with mem_lock:
            return read_text_state(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool()
    def press_button(
        button: Button,
        hold_frames: int = 10,
        settle_frames: int = 8,
    ) -> str:
        """Press a button on the emulator.

        Args:
            button: The name of the button to press
                (e.g., Button.A, Button.B, Button.UP, Button.DOWN).
            hold_frames: The number of frames to hold the button down (default is 10).
            settle_frames: The number of frames to wait after releasing the button,
                so the game can react (default is 8).
        Returns:
            A string indicating which button was pressed and for how many frames.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            pyboy.button(
                button.value,
                delay=hold_frames,
            )
            pyboy.tick(hold_frames + settle_frames)
        return f"Pressed {button.name} for {hold_frames} frames"

    @mcp.tool()
    def advance_frames(frames: int) -> str:
        """Advance the emulator by a given number of frames.

        Args:
            frames: The number of frames to advance.
        Returns:
            A string indicating how many frames were advanced.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
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
