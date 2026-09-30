# Bug findings from the first playthrough (Pallet Town → Boulder Badge)

Found by playing a fresh save through the agent-oak MCP server up to and including
the Brock fight (2026-09-30). Everything worked end to end. The issues below are
data-accuracy problems and small usability gaps.

## 1. `get_party` returns garbage stats

**Observed**

| When | attack | defense | speed | special |
|------|--------|---------|-------|---------|
| Squirtle Lv6 (Route 1) | 12544 | 49 | 12544 | 45 |
| Squirtle Lv10 (Viridian Forest) | 64258 | 529 | 4354 | 658 |

`12544 == 0x3100`. The real values at these levels are about 10–30. Level, HP, max HP,
moves, PP, OT and experience from the same call were all correct.

**Where:** `agent_oak/memory/read.py`, `_parse_pokemon`. It reads the stats with
`u16_big_endian` at `0x24/0x26/0x28/0x2A`. Those offsets match pokered's
`party_struct`, and `max_hp` at `0x22` reads correctly with the same helper, so the
offsets alone don't explain it. Things to check:
- the exact bytes at `wPartyMon1 + 0x22..0x2B` in a live session
- whether the symbol file or ROM version matches the struct layout
- whether something writes to that range during menus or battle

**Fix / test:** add a unit test with a known party-struct byte dump, and check that
the stats are plausible (for example, Lv6 Squirtle attack ≈ 11–13).

## 2. `get_battle_state.battle_type` is always `"WILD"`

**Observed:** it returned `"WILD"` during the rival battle (Blue), the Bug Catchers,
the Jr. Trainer and Brock.

**Where:** `agent_oak/memory/read.py` (`read_battle_state`, around line 800) builds it
from `wIsInBattle`. In pokered, `wIsInBattle` is `1` for wild and `2` for trainer
battles, so either the wrong address is being read or the value gets reset before
the read. `wIsInBattle` changes during the battle intro, so check it partway through
a trainer battle. `wCurOpponent >= OPP_ID_OFFSET (200)` might be a more reliable way
to tell trainer battles apart.

This also affects `enemy_out`: the `ENEMY_NOT_LOADED` guard only applies to
`BattleType.TRAINER`, so it never runs.

## 3. Stale battle state at battle start

**Observed:** calling `get_battle_state` right after `goto_map` returned
`status: in_battle`, before the "Wild X appeared!" text had been advanced, gave:

```json
"player_pokemon": {"species_id": 0, "species": "NO_MON", "level": 6, "hp": 6, "max_hp": 21, ...}
```

HP 6/21 was from the previous battle. The party had just been fully healed.

**Expected:** `player_pokemon: null`, or read the values from the party, while
`wBattleMonSpecies == 0`. The `player_out` check exists, but the result still
contained a partly built Pokémon. It's possible the check isn't applied on every
code path, for example the one used by `use_move`/`goto_map` results.

## 4. Stray "But, it failed!" in move results

**Observed:** some `use_move` results started or ended with `But, it failed!` where
the enemy's turn text should have been, for example:

```
"But, it failed!\nSQUIRTLE\nused TACKLE!"
"SQUIRTLE\nused TACKLE!\nBut, it failed!"
```

Nothing in the battle had actually failed. HP changed as expected, so the enemy's
line (probably a Tail Whip or Growl turn, or a message shown only briefly) was
replaced by leftover text.

**Where:** probably `agent_oak/executor/dialogue.py`, when it reads the text box.
Stale tile or text-buffer content is read before the new text is printed.

## 5. Options screen parsed as one menu option

**Observed:** selecting `OPTION` on the title menu gave
`menu: {"kind": "menu", "options": ["MEDIUM SLOW"], "selected": 0}`. The screen
really has three rows (TEXT SPEED / BATTLE ANIMATION / BATTLE STYLE), each with
left/right choices. I had to set it with raw `press_button`.

**Suggestion:** detect the options screen and either report it as its own `kind`
(for example `options` with the current values), or add a small `set_options` tool
(text speed, animation, style). An agent will almost always want FAST, OFF and SET.

## 6. `goto_map` gives up one tile short of gate warps

**Observed:**
```
goto_map("VIRIDIAN_FOREST_SOUTH_GATE")
→ {"reached": false, "status": "gave_up", "goal": {x: 4, y: 0}, "location": {x: 4, y: 1}}
```
Without x/y, the default target is the map's *first* warp. In a gate, that warp is
the exit into the forest at the top edge (y=0), which you enter by stepping up from
y=1. Passing an explicit target inside `VIRIDIAN_FOREST` worked.

**Suggestions:**
- When the goal tile is a warp, treat "stepped onto the warp / changed map" as
  reached, and allow the final step onto edge warps.
- When you target a map you're already on, the default "first warp" probably
  shouldn't be the goal at all.

## 7. Small usability gaps

- `goto_map("ROUTE_1")` without coordinates returns
  `"ROUTE_1 has no warps, pass x and y"`. Maps with no warps could default to the
  connection edge nearest the player, or to the center of the map.
- The Mart's `BUY` list stays open after `buy_item_tool`. To leave, I needed
  `press_button(b)` → `advance_dialogue_tool` → `select_option_tool(2)` (QUIT).
  A `close: true` flag, or a `leave_mart` helper, would save three calls.
- The `get_location` payload includes the raw `blocks` string, which is large and
  unreadable in tool output. Consider leaving it out by default, since `get_map`
  already renders it.

## What worked well

- `talk_to_tool` handled trainers, items and nurses, including walking into a
  trainer's line of sight and starting the battle.
- `goto_map` stops cleanly at wild battles and trainer interrupts, and resumes well.
- `advance_dialogue_tool` got through the whole Oak intro and parcel scene with
  only one timeout continuation.
- `use_move`, `use_item_tool` (in and out of battle), `buy_item_tool` and
  `run_from_battle` all did what they say. The "not in list" error for mart items
  lists the stock, which is very helpful.

## Save state context

State at the end of the session: Pewter Gym after Brock, 1 badge, Squirtle Lv15
(Tackle / Tail Whip / Bubble / Water Gun), 4 Potions, 5 Poké Balls, TM34 (Bide).
