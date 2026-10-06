"""Server for the Pokemon MCP."""

from threading import Lock

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pyboy import PyBoy

from agent_oak.executor.battle import battle_run, battle_switch, battle_use_move
from agent_oak.executor.dialogue import (
    advance_dialogue,
    choose_quantity,
    select_option,
    talk_to,
)
from agent_oak.executor.graph import nearest_node
from agent_oak.executor.items import buy_item, sell_item, use_item
from agent_oak.executor.models import TalkResult, World
from agent_oak.executor.navigation import _get_current_node, goto
from agent_oak.executor.options import set_options
from agent_oak.memory.models import (
    BagItems,
    BattleAnimation,
    BattleState,
    BattleStyle,
    BattleTurn,
    Button,
    DialogueResult,
    GameOptions,
    MapObjects,
    ObtainedBadges,
    PlayerLocation,
    Pokemon,
    TextSpeed,
    TextState,
)
from agent_oak.memory.read import (
    read_badges,
    read_bag,
    read_battle_state,
    read_location,
    read_map_objects,
    read_options,
    read_party,
    read_text_state,
)
from agent_oak.memory.render_map import render_current_map
from agent_oak.objectives.tracker import ObjectiveTracker
from agent_oak.parser.maps import search_maps
from agent_oak.parser.models import GameMap, MapInfo
from agent_oak.pyboy_mcp.emulator import grab_screen_png, running
from agent_oak.pyboy_mcp.objectives import ACTION_TAG, add_objective_tools


def build_server(
    pyboy: PyBoy,
    symbols: dict[str, int],
    maps_by_id: dict[int, GameMap],
    world: World,
    mem_lock: Lock,
    tracker: ObjectiveTracker | None = None,
) -> FastMCP:
    """Build the MCP server with the given emulator and symbols.

    Args:
        pyboy: The emulator instance to read from.
        symbols: The symbol table mapping names to addresses.
        maps_by_id: Parsed game maps keyed by map id.
        world: The world model used for pathfinding, its maps are keyed by const.
        mem_lock: A lock to synchronize access to the emulator's memory.
        tracker: Objective tracker, adds the objective tools and the status
            line on action tools. None leaves the objective layer out.
    Returns:
        An instance of FastMCP with the defined tools.
    """
    mcp = FastMCP(
        name="agent-oak",
    )

    @mcp.tool(tags={ACTION_TAG})
    def advance_dialogue_tool(timeout_frames: int = 1800) -> DialogueResult:
        """Read and click through text until it ends or a choice is needed.

        Only presses A on finished pages, never inside menus. Stops at yes/no
        prompts and other menus (answer with select_option_tool), at the
        battle menu (FIGHT / PKMN / ITEM / RUN) and at quantity prompts
        (answer with choose_quantity_tool). Waits through scripted scenes
        like an NPC walking the player somewhere.

        Args:
            timeout_frames: Frame budget, call again after a timeout to go on.
        Returns:
            'status' (done, menu, battle_menu, quantity or timeout), every
                line shown in order, and the menu or quantity prompt waiting
                for an answer, if any.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return advance_dialogue(
                pyboy=pyboy,
                syms=symbols,
                timeout_frames=timeout_frames,
            )

    @mcp.tool(tags={ACTION_TAG})
    def select_option_tool(index: int, timeout_frames: int = 1800) -> DialogueResult:
        """Choose an option of the open menu and read what follows.

        Works for any menu the dialogue tools report: yes/no prompts,
        Pokecenter, start menu, item lists (bag, mart, the whole list, it
        scrolls as needed), and in battle the FIGHT / PKMN / ITEM / RUN menu,
        the move list and the party list. Prefer use_move, switch_pokemon,
        run_from_battle, use_item, buy_item and sell_item, they pick by name.

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

    @mcp.tool(tags={ACTION_TAG})
    def choose_quantity_tool(
        quantity: int,
        timeout_frames: int = 1800,
    ) -> DialogueResult:
        """Answer a ×NN quantity prompt (buy, sell, toss) and read what follows.

        Args:
            quantity: How many, 1 up to the prompt's max.
            timeout_frames: Frame budget for the dialogue after the choice.
        Returns:
            The dialogue after the choice, like advance_dialogue_tool.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return choose_quantity(
                pyboy=pyboy,
                syms=symbols,
                quantity=quantity,
                timeout_frames=timeout_frames,
            )

    @mcp.tool(tags={ACTION_TAG})
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

    @mcp.tool(tags={ACTION_TAG})
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
            x: Target x in steps. Omit x and y to just enter the map, by the
                closest warp or map edge.
            y: Target y in steps, see x.
        Returns:
            Whether the goal was reached, the goal, where the player ended up
                and 'status': "reached" (a warp goal counts as reached when
                it warped the player), "in_battle", "dialogue_open",
                "no_path" (goal unreachable from here) or "gave_up" (kept
                getting blocked, e.g. by moving NPCs).
        """
        target = world.maps.get(map_const)
        if target is None or map_const == "LAST_MAP":
            return {"reached": False, "error": f"Unknown map {map_const}"}
        if (x is None) != (y is None):
            return {"reached": False, "error": "Pass both x and y, or neither"}

        enter_only = x is None
        with running(pyboy=pyboy, mem_lock=mem_lock):
            start = _get_current_node(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
            )
            if x is None or y is None:
                if start[0] == map_const:
                    return {
                        "reached": True,
                        "status": "reached",
                        "note": f"Already on {map_const}, pass x and y to "
                        "walk somewhere on it",
                        "location": {"map": start[0], "x": start[1], "y": start[2]},
                    }
                # the first tile of the map on the way there, the warp or
                # map edge the player enters it by
                entry = nearest_node(
                    world=world,
                    start=start,
                    is_goal=lambda n: n[0] == map_const,
                )
                if entry is None:
                    return {
                        "reached": False,
                        "status": "no_path",
                        "error": f"No path to {map_const}",
                    }
                _, x, y = entry

            goal = (map_const, x, y)
            # some warps sit on solid tiles, they are still reachable through
            # the warp edge that lands on them
            is_warp = any((w.x, w.y) == (x, y) for w in target.warps)
            if not is_warp and world.terrain(node=goal) is None:
                return {
                    "reached": False,
                    "error": f"{goal} is out of bounds or not walkable",
                }

            status = goto(
                pyboy=pyboy,
                syms=symbols,
                maps_by_id=maps_by_id,
                world=world,
                goal=goal,
                any_tile=enter_only,
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

    @mcp.tool(tags={ACTION_TAG})
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

    @mcp.tool(tags={ACTION_TAG})
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

    @mcp.tool(tags={ACTION_TAG})
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

    @mcp.tool(tags={ACTION_TAG})
    def use_item_tool(
        item: str,
        target: str | None = None,
    ) -> BattleTurn | DialogueResult:
        """Use an item from the bag, in battle or on the overworld.

        In battle it is the turn's action (POTION, POKé BALL, ...), outside
        of battle it opens the start menu, uses the item and closes the
        menus again.

        Args:
            item: Item name as in get_bag, e.g. "POTION" or "POKE_BALL".
            target: Nickname of the party Pokemon for items like POTION.
                Defaults to the active Pokemon in battle and to the only
                party Pokemon outside of it.
        Returns:
            In battle the turn and battle state, like use_move. Outside of
                battle the dialogue. Follow up prompts (nickname a caught
                Pokemon, teach a TM, ...) come back as a menu.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return use_item(
                pyboy=pyboy,
                syms=symbols,
                item=item,
                target=target,
            )

    @mcp.tool(tags={ACTION_TAG})
    def buy_item_tool(
        item: str,
        quantity: int = 1,
        close: bool = False,
    ) -> DialogueResult:
        """Buy an item at a mart, after talking to the clerk (talk_to_tool).

        Works from the clerk's BUY / SELL / QUIT menu or an open list.

        Args:
            item: Item name as listed by the clerk, e.g. "POKE BALL".
            quantity: How many to buy.
            close: Leave the mart menus afterwards (CANCEL, then QUIT).
        Returns:
            The clerk's answer and the menu after it: the buy list again to
                buy more, or BUY / SELL / QUIT when the money was not
                enough. With close, the dialogue up to the clerk's goodbye.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return buy_item(
                pyboy=pyboy,
                syms=symbols,
                item=item,
                quantity=quantity,
                close=close,
            )

    @mcp.tool(tags={ACTION_TAG})
    def sell_item_tool(
        item: str,
        quantity: int = 1,
        close: bool = False,
    ) -> DialogueResult:
        """Sell an item from the bag at a mart, after talking to the clerk.

        Args:
            item: Item name as in get_bag, e.g. "ANTIDOTE".
            quantity: How many to sell, capped at the number in the bag.
            close: Leave the mart menus afterwards (CANCEL, then QUIT).
        Returns:
            The clerk's answer and the menu after it.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return sell_item(
                pyboy=pyboy,
                syms=symbols,
                item=item,
                quantity=quantity,
                close=close,
            )

    @mcp.tool()
    def get_options() -> GameOptions:
        """Get the game settings: text speed, battle animation and style.

        Returns:
            The settings as the OPTION screen shows them.
        """
        with mem_lock:
            return read_options(
                pyboy=pyboy,
                syms=symbols,
            )

    @mcp.tool(tags={ACTION_TAG})
    def set_options_tool(
        text_speed: TextSpeed | None = "FAST",
        battle_animation: BattleAnimation | None = "OFF",
        battle_style: BattleStyle | None = "SET",
    ) -> GameOptions:
        """Change the game settings on the OPTION screen.

        Opens the screen from the title menu, the start menu or the
        overworld (not in battle), sets the values and closes it again. The
        defaults make the game fastest to play.

        Args:
            text_speed: FAST, MEDIUM or SLOW, None keeps the current value.
            battle_animation: ON or OFF, None keeps the current value.
            battle_style: SHIFT or SET, None keeps the current value.
        Returns:
            The settings after the change.
        """
        with running(pyboy=pyboy, mem_lock=mem_lock):
            return set_options(
                pyboy=pyboy,
                syms=symbols,
                text_speed=text_speed,
                battle_animation=battle_animation,
                battle_style=battle_style,
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

    @mcp.tool(tags={ACTION_TAG})
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

    @mcp.tool(tags={ACTION_TAG})
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

    if tracker is not None:
        add_objective_tools(mcp=mcp, tracker=tracker)

    return mcp
