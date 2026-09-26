# AgentOak

An LLM playing Pokémon Red in a meaningful way. Instead of mashing buttons from screenshots, the model gets structured game state and high-level actions over [MCP](https://modelcontextprotocol.io), so it can plan and reason about the game.

> **Status:** early work in progress. The emulator bridge and memory readers work. The world model and pathfinding exist but are not yet connected to the MCP tools.

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
- **`agent_oak/executor`**: actions that span many frames: dialogue advancing, greedy `walk_to`, and the new `World` model with A* `shortest_path` over tiles, warps, map connections and ledges.

### MCP tools

| Tool | Purpose |
| --- | --- |
| `get_party`, `get_bag`, `get_badges`, `get_location` | Player state |
| `get_battle_state`, `get_dialogue` | Battle and text state |
| `get_screenshot` | Current screen as PNG |
| `press_button`, `advance_frames` | Raw input |
| `advance_dialogue_tool` | Click through text until it ends or a yes/no prompt appears |
| `walk_to_tool` | Walk to a tile on the current map (greedy, bump detection) |

## Getting started

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Graphviz (for `pygraphviz`). The ROM is not included: place your own `pokemon-red.gb` in the repo root.

```sh
uv sync
uv run agentoak   # starts PyBoy + MCP server on http://127.0.0.1:8765/mcp
```

By default the game is paused and only advances inside acting tools, so it doesn't drift while the LLM thinks. Use `uv run agentoak --manual` to start unpaused and play by hand. Press **P** in the emulator window at any time to toggle pause.

Then point any MCP client at the server. `.vscode/mcp.json` has a ready-made config.
`scripts/render_map_graph.py` renders the map connectivity graph to PDF.

## Roadmap

- [ ] Connect the `World` / A* pathfinder to MCP (replace the greedy `walk_to`)
- [ ] Account for NPCs, story progression and HM abilities (Cut, Surf, ...) during pathfinding
- [ ] Resolve `LAST_MAP` warps at runtime
- [ ] Battle actions (use move, switch, run)
- [ ] Talk-to-NPC and menu/item actions
- [ ] Interrupt handling (wild battles, dialogues) during multi-step actions
- [ ] Objective layer: let the LLM query what it has achieved (badges, key items, story flags) and what it still needs to do next
- [ ] Memory layer for long-horizon play
- [ ] Tests

## Credits

Map, constant and graphics data come from the [pret/pokered](https://github.com/pret/pokered) disassembly. Emulation by [PyBoy](https://github.com/Baekalfen/PyBoy).
