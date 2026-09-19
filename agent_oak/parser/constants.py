"""Parse assembly constants and charmap entries used by the emulator helpers."""

import re
from functools import lru_cache
from pathlib import Path

_RE_CONST_DEF = re.compile(
    r"^\s*const_def\b(.*)$",
    re.IGNORECASE,
)
_RE_CONST = re.compile(
    r"^\s*const\s+(\w+)",
    re.IGNORECASE,
)
_RE_ADD_TM_HM = re.compile(
    r"^\s*(?:add_tm|add_hm)\s+(\w+)",
    re.IGNORECASE,
)
_RE_CONST_SKIP = re.compile(
    r"^\s*const_skip\b(.*)$",
    re.IGNORECASE,
)
_RE_EQU = re.compile(
    r"^\s*(?:DEF\s+)?(\w+)\s+EQU\s+(.+)$",
    re.IGNORECASE,
)
_RE_CHARMAP = re.compile(
    r'^\s*charmap\s+"([^"]+)"\s*,\s*(.+)$',
    re.IGNORECASE,
)


def _strip_comments(s: str) -> str:
    """Strip comments from a line of assembly code.

    Args:
        s: The line of code to strip comments from.
    Returns:
        The line of code with comments removed.
    """
    return s.split(";", 1)[0].strip()


def _eval_value(expr: str, scope: dict[str, int]) -> int | None:
    """Evaluate a constant expression.

    Args:
        expr: The expression to evaluate.
        scope: A dictionary of constant names to their values.
    Returns:
        The evaluated value of the expression, or None if it cannot be evaluated.
    """
    expr = _strip_comments(expr)

    if not expr:
        return None

    if re.fullmatch(r"\$[0-9A-Fa-f]+", expr):
        return int(expr[1:], 16)
    if re.fullmatch(r"0x[0-9A-Fa-f]+", expr):
        return int(expr[2:], 16)
    if re.fullmatch(r"%[01]+", expr):
        return int(expr[1:], 2)
    if re.fullmatch(r"\d+", expr):
        return int(expr)
    if re.fullmatch(r"\w+", expr) and expr in scope:
        return scope[expr]
    return None


def parse_asm_constants(text: str) -> dict[str, int]:
    """Parse constants from assembly code.

    Args:
        text: The assembly code to parse.
    Returns:
        A dictionary of constant names to their values.
    """
    syms = {}
    counter = 0

    for line in text.splitlines():
        if m := _RE_CONST_DEF.match(line):
            arg = _strip_comments(m.group(1))
            v = _eval_value(arg, syms) if arg else None
            counter = v if v is not None else 0
            continue

        if m := _RE_CONST.match(line):
            syms[m.group(1)] = counter
            counter += 1
            continue

        if m := _RE_ADD_TM_HM.match(line):
            syms[m.group(1)] = counter
            counter += 1
            continue

        if m := _RE_EQU.match(line):
            name, val = m.group(1), m.group(2)
            v = _eval_value(val, syms)
            if v is not None:
                syms[name] = v

        if m := _RE_CHARMAP.match(line):
            name, val = m.group(1), m.group(2)
            v = _eval_value(val, syms)
            if v is not None:
                syms[name] = v

        if m := _RE_CONST_SKIP.match(line):
            counter += 1
            continue

    return syms


@lru_cache(maxsize=None)
def load_constants(path: Path) -> dict[str, int]:
    """Load constants from an assembly file.

    Args:
        path: The path to the assembly file.
    Returns:
        A dictionary of constant names to their values.
    """
    with path.open("r", encoding="utf-8") as f:
        text = f.read()
    return parse_asm_constants(text)


def by_id(path: Path, exclude: tuple[str, ...] = ()) -> dict[int, str]:
    """Load constants from an assembly file and return a mapping of values to names.

    Args:
        path: The path to the assembly file.
        exclude: A tuple of constant names to exclude from the mapping.
    Returns:
        A dictionary of constant values to their names.
    """
    syms = load_constants(path)
    out = {}
    for name, value in syms.items():
        if name in exclude or value in out:
            continue
        out[value] = name
    return out


if __name__ == "__main__":
    dict = parse_asm_constants(Path("constants/map_constants.asm").read_text())
    print(dict)
