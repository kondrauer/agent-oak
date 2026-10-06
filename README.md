# AgentOak

An LLM playing Pokémon Red in a meaningful way. Instead of mashing buttons from screenshots, the model gets structured game state and high-level actions over [MCP](https://modelcontextprotocol.io), so it can plan and reason about the game.

> **Status:** work in progress. Using only the MCP tools, an LLM played a new save from Pallet Town to the Boulder Badge. The issues found in that run, and how they were fixed, are in [BUGS.md](BUGS.md).

## How it works

```
LLM client ──MCP (HTTP)──▶ FastMCP server ──▶ PyBoy (Pokémon Red)
                                │
                                ├─ memory/    reads RAM via pokered.sym symbols
                                ├─ executor/  multi-step actions (dialogue, walking, ...)
                                └─ parser/    static world data from the pokered disassembly
```

- **`agent_oak/pyboy_mcp`**: the emulator wrapper and the MCP server that exposes the tools.
- **`agent_oak/memory`**: typed readers for party, bag, badges, location, battle state, dialogue text, warps and NPCs, plus an ASCII render of the current map.
- **`agent_oak/parser`**: parses the [pokered](https://github.com/pret/pokered) sources (`constants/`, `data/maps/`, `maps/*.blk`, `gfx/`) into maps, warps, connections, objects, tilesets and collision data.
- **`agent_oak/executor`**: actions that span many frames: advancing dialogue, battle, item and mart actions, and the `World` model with A* `shortest_path` over tiles, warps, map connections and ledges. Multi-step actions stop early at interrupts (wild battles, trainers spotting the player, text boxes) and report why. The caller handles the interrupt and calls again to continue.

### MCP tools

| Tool | Purpose |
| --- | --- |
| `get_party`, `get_bag`, `get_badges`, `get_location` | Player state |
| `get_battle_state`, `get_dialogue` | Battle state, text box contents and open menu |
| `get_screenshot` | Current screen as PNG |
| `press_button`, `advance_frames` | Raw input |
| `advance_dialogue_tool` | Read and click through text page by page, stops at menus, prompts and the battle menu |
| `select_option_tool` | Pick an option of the open menu (yes/no, Pokecenter, battle menus, bag and mart lists, ...) and read what follows |
| `choose_quantity_tool` | Answer a ×NN quantity prompt (buy, sell, toss) and read what follows |
| `use_move`, `switch_pokemon`, `run_from_battle` | Battle actions by name, return the turn's text and the battle state |
| `use_item_tool`, `buy_item_tool`, `sell_item_tool` | Use an item in or out of battle, buy and sell at a mart, by name (`close` leaves the mart menus) |
| `get_options`, `set_options_tool` | Read and change text speed, battle animation and battle style |
| `talk_to_tool` | Walk next to an NPC or sign (also across counters), face it and talk |
| `get_npcs` | NPCs with live positions and their map data, plus the map's signs |
| `find_maps` | Search maps by name substring, returns warps, connections, objects and signs |
| `goto_map` | A* walk into a map or to an `x, y` on any map, replans around NPCs |
| `get_map` | ASCII render of the current map in step coordinates, to pick `goto_map` targets |

## Getting started

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Graphviz (for `pygraphviz`). The ROM is not included: place your own `pokemon-red.gb` in the repo root.

```sh
uv sync
uv run agentoak   # starts PyBoy + MCP server on http://127.0.0.1:8765/mcp
```

By default the game is paused and only advances inside acting tools, so it doesn't drift while the LLM thinks. Use `uv run agentoak --manual` to start unpaused and play by hand. Press **P** in the emulator window at any time to toggle pause.

Tools skip ahead many frames at once, so the window only updates now and then. `--realtime` shows every frame at real speed instead, tools take as long as the game does. `--record run.mp4` (needs ffmpeg, implies `--realtime`) records every frame the game advances, paused time between tool calls is left out. Cut a part into a GIF with:

```sh
ffmpeg -ss 00:12:30 -to 00:14:00 -i run.mp4 \
  -vf "fps=30,scale=320:-1:flags=neighbor,split[a][b];[a]palettegen[p];[b][p]paletteuse" brock.gif
```

Then point any MCP client at the server. `.vscode/mcp.json` has a ready-made config.
`scripts/render_map_graph.py` renders the map connectivity graph to PDF.

## Roadmap

- [x] Connect the `World` / A* pathfinder to MCP (replace the greedy `walk_to`)
- [x] Account for NPCs, story progression and HM abilities (Cut, Surf, ...) during pathfinding
- [x] Resolve `LAST_MAP` warps at world building time
- [x] Battle actions (use move, switch, run)
- [x] Items in and out of battle, buying and selling (scrolling list menus)
- [ ] TMs and HMs (teach, replace a move, field moves like CUT)
- [x] Talk-to-NPC and menu/item actions
- [x] Interrupt handling (wild battles, dialogues) during multi-step actions
- [x] Beat the first gym end to end over MCP
- [x] Fix the playtest findings in [BUGS.md](BUGS.md) (party stats, battle type, stale battle text, options screen, gate warps)
- [ ] Objective layer: let the LLM query what it has achieved (badges, key items, story flags) and what it still needs to do next
- [ ] Memory layer for long-horizon play
- [ ] Tests

## Credits

Map, constant and graphics data come from the [pret/pokered](https://github.com/pret/pokered) disassembly. Emulation by [PyBoy](https://github.com/Baekalfen/PyBoy).
