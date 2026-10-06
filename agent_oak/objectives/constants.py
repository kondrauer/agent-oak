"""Extract the constant tables the objective layer needs from pokered.

The result is written to data/constants.json by scripts/extract_constants.py,
so the objectives load without parsing assembly at startup.
"""

import json
import re
from pathlib import Path
from typing import Any

from agent_oak.parser.constants import parse_asm_constants

CONSTANTS_PATH = Path("data/constants.json")
BADGE_BIT = re.compile(r"^BIT_(\w+)BADGE$")
STATUS_FLAGS_SECTION = re.compile(r"^; (wStatusFlags\d)\s*$")
_RE_TOGGLE_FOR = re.compile(r"^\s*(?:toggleable|missable)_objects_for\s+(\w+)")
_RE_TOGGLE_STATE = re.compile(
    r"^\s*(?:toggle_object_state|missable_object_state)\s+([\w$]+)\s*,\s*(\w+)"
)
# older pokered checkouts call toggleable objects "missable" / hide-show
_RE_OLD_TOGGLE_STATE = re.compile(r"^\s*db\s+(\w+)\s*,\s*(\w+)\s*,\s*(SHOW|HIDE)\b")


def _detect_toggle_naming(root: Path) -> tuple[str, Path, Path]:
    """Find the toggleable object files of this checkout.

    Returns:
        The naming ("toggleable" or "missable"), the constants file and the
            data file listing every object's map and initial state.
    """
    new = (
        root / "constants/toggle_constants.asm",
        root / "data/maps/toggleable_objects.asm",
    )
    old = (
        root / "constants/hide_show_constants.asm",
        root / "data/maps/hide_show_data.asm",
    )
    if all(p.exists() for p in new):
        return "toggleable", *new
    if all(p.exists() for p in old):
        return "missable", *old
    raise FileNotFoundError(
        f"No toggleable or missable object constants under {root}, looked for "
        f"{new[0]} and {old[0]}"
    )


def _parse_toggle_objects(data: str) -> list[tuple[str, str, str]]:
    """Map and object of every toggleable object, in TOGGLE_* index order.

    Returns:
        (map const, object const, initial state ON / OFF) per entry.
    """
    out: list[tuple[str, str, str]] = []
    current_map: str | None = None
    for line in data.splitlines():
        line = line.split(";", 1)[0]
        if m := _RE_TOGGLE_FOR.match(line):
            current_map = m.group(1)
        elif (m := _RE_TOGGLE_STATE.match(line)) and current_map is not None:
            out.append((current_map, m.group(1), m.group(2)))
        elif m := _RE_OLD_TOGGLE_STATE.match(line):
            state = "ON" if m.group(3) == "SHOW" else "OFF"
            out.append((m.group(1), m.group(2), state))
    return out


def _parse_status_flags(text: str) -> dict[str, dict[str, Any]]:
    """Bits of wStatusFlags1-7, e.g. GAVE_SAFFRON_GUARDS_DRINK in flags 1.

    ram_constants.asm has a section per variable, headed by a "; wName"
    comment, each enumerating its bits from const_def.
    """
    flags: dict[str, dict[str, Any]] = {}
    sections = re.split(r"(?m)^(?=; w)", text)
    for section in sections:
        header = section.splitlines()[0] if section else ""
        m = STATUS_FLAGS_SECTION.match(header)
        if m is None:
            continue
        for name, bit in parse_asm_constants(section, aliases=False).items():
            if name.startswith("BIT_"):
                flags[name.removeprefix("BIT_")] = {"symbol": m.group(1), "bit": bit}
    return flags


def build_constants(root: Path = Path(".")) -> dict[str, Any]:
    """Parse every table the objective layer needs from a pokered checkout.

    Args:
        root: The pokered checkout, the repo root has the files vendored.
    Returns:
        A JSON-serializable dict: event flag bit indices, toggleable objects,
            item, move, species and map ids, town, badge and status flag
            bits.
    """

    def consts(path: str, **kwargs: Any) -> dict[str, int]:
        return parse_asm_constants((root / path).read_text(), **kwargs)

    event_consts = consts("constants/event_constants.asm")
    num_events = event_consts.pop("NUM_EVENTS")
    events = {k: v for k, v in event_consts.items() if k.startswith("EVENT_")}

    naming, toggle_consts_path, toggle_data_path = _detect_toggle_naming(root)
    prefix = "TOGGLE_" if naming == "toggleable" else "HS_"
    toggle_ids = {
        k: v
        for k, v in parse_asm_constants(toggle_consts_path.read_text()).items()
        if k.startswith(prefix)
    }
    entries = _parse_toggle_objects(toggle_data_path.read_text())
    toggles = {}
    for name, index in toggle_ids.items():
        if index >= len(entries):
            raise ValueError(f"{name} = {index} has no entry in {toggle_data_path}")
        map_const, obj, state = entries[index]
        toggles[name] = {"index": index, "map": map_const, "object": obj}
        toggles[name]["initially_shown"] = state == "ON"

    def table(path: str, skip: tuple[str, ...], **kwargs: Any) -> dict[str, int]:
        return {
            k: v
            for k, v in consts(path, aliases=False, **kwargs).items()
            if k not in skip and v != 0
        }

    items = table("constants/item_constants.asm", ("NO_ITEM",), tmhm_prefix=True)
    # ids after the last move are battle animations
    num_moves = consts("constants/move_constants.asm")["NUM_ATTACKS"]
    moves = {
        k: v
        for k, v in table("constants/move_constants.asm", ("NO_MOVE",)).items()
        if v <= num_moves
    }
    species = table("constants/pokemon_constants.asm", ("NO_MON",))
    num_city_maps = consts("constants/map_constants.asm")["NUM_CITY_MAPS"]
    maps = table("constants/map_constants.asm", ())
    maps["PALLET_TOWN"] = 0
    # wTownVisitedFlag has one bit per city map, set on entering it
    towns = {k: v for k, v in maps.items() if v < num_city_maps}
    badges = {
        m.group(1): v
        for k, v in consts("constants/ram_constants.asm").items()
        if (m := BADGE_BIT.match(k))
    }
    status_flags = _parse_status_flags(
        (root / "constants/ram_constants.asm").read_text()
    )

    return {
        "toggle_naming": naming,
        "num_events": num_events,
        "events": events,
        "toggles": toggles,
        "items": items,
        "moves": moves,
        "species": species,
        "maps": maps,
        "towns": towns,
        "badges": badges,
        "status_flags": status_flags,
    }


def write_constants(root: Path = Path("."), out: Path = CONSTANTS_PATH) -> None:
    """Build the constant tables and write them as JSON."""
    out.write_text(json.dumps(build_constants(root=root), indent=1) + "\n")


def load_constants_json(path: Path = CONSTANTS_PATH) -> dict[str, Any]:
    """Load the tables written by write_constants."""
    return json.loads(path.read_text())
