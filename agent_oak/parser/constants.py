"""Parse assembly constants and charmap entries used by the emulator helpers."""

import ast
import operator
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

_RE_CONST_DEF = re.compile(
    r"^\s*const_def\b(.*)$",
    re.IGNORECASE,
)
_RE_CONST = re.compile(
    r"^\s*(?:const|const_export|map_const)\s+(\w+)",
    re.IGNORECASE,
)
_RE_ADD_TM_HM = re.compile(
    r"^\s*(add_tm|add_hm)\s+(\w+)",
    re.IGNORECASE,
)
_RE_CONST_SKIP = re.compile(
    r"^\s*const_skip\b(.*)$",
    re.IGNORECASE,
)
_RE_CONST_NEXT = re.compile(
    r"^\s*const_next\b(.*)$",
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
_RE_MACRO = re.compile(r"^\s*MACRO\??\s", re.IGNORECASE)
_RE_ENDM = re.compile(r"^\s*ENDM\b", re.IGNORECASE)
_RE_NUMBER = re.compile(r"\$([0-9A-Fa-f]+)|%([01]+)")
_BIN_OPS: dict[type[ast.operator], Callable[[int, int], int]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
}


def _strip_comments(s: str) -> str:
    """Strip comments from a line of assembly code.

    Args:
        s: The line of code to strip comments from.
    Returns:
        The line of code with comments removed.
    """
    return s.split(";", 1)[0].strip()


def _eval_value(expr: str, scope: dict[str, int]) -> int | None:
    """Evaluate a constant expression like `$F0 - 2` or `1 << BIT_X`.

    Supports rgbasm number literals ($hex, %binary, decimal), names from
    'scope' and integer arithmetic.

    Args:
        expr: The expression to evaluate.
        scope: A dictionary of constant names to their values.
    Returns:
        The evaluated value of the expression, or None if it cannot be evaluated.
    """
    expr = _strip_comments(expr)
    if not expr:
        return None

    def literal(m: re.Match[str]) -> str:
        hex_digits, bin_digits = m.groups()
        return str(int(hex_digits, 16) if hex_digits else int(bin_digits, 2))

    # rgbasm's / is integer division
    expr = _RE_NUMBER.sub(literal, expr).replace("/", "//")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def ev(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name):
            return scope[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        raise ValueError(node)

    try:
        return ev(tree)
    except (KeyError, ValueError, ZeroDivisionError):
        return None


def parse_asm_constants(
    text: str,
    tmhm_prefix: bool = False,
    aliases: bool = True,
) -> dict[str, int]:
    """Parse constants from assembly code.

    Implements pokered's macros/const.asm: `const_def [start[, inc]]`,
    `const`, `const_export`, `const_skip [n]` and `const_next value`, plus
    `map_const`, `add_tm` / `add_hm`, EQU definitions and charmap entries.

    Macro definitions are skipped. Enumerated names come first in the result,
    so by_id prefers them over EQU aliases of the same value (HM01 = HM_CUT).

    Args:
        text: The assembly code to parse.
        tmhm_prefix: Name TMs and HMs like the disassembly does (HM_CUT,
            TM_MEGA_PUNCH) instead of just the move name.
        aliases: Include EQU definitions, otherwise only enumerated names
            (const, add_tm, ...) and charmap entries.
    Returns:
        A dictionary of constant names to their values.
    """
    syms: dict[str, int] = {}
    equs: dict[str, int] = {}
    counter = 0
    inc = 1
    in_macro = False

    for line in text.splitlines():
        if in_macro:
            in_macro = not _RE_ENDM.match(line)
            continue
        if _RE_MACRO.match(line):
            in_macro = True
            continue

        if m := _RE_CONST_DEF.match(line):
            args = [a.strip() for a in _strip_comments(m.group(1)).split(",") if a]
            start = _eval_value(args[0], syms | equs) if args else None
            step = _eval_value(args[1], syms | equs) if len(args) > 1 else None
            counter = start if start is not None else 0
            inc = step if step is not None else 1
            syms["const_value"] = counter
            continue

        if m := _RE_CONST.match(line):
            syms[m.group(1)] = counter
            counter += inc
            syms["const_value"] = counter
            continue

        if m := _RE_ADD_TM_HM.match(line):
            kind, name = m.group(1).lower(), m.group(2)
            prefix = ("HM_" if kind == "add_hm" else "TM_") if tmhm_prefix else ""
            syms[prefix + name] = counter
            counter += inc
            syms["const_value"] = counter
            continue

        if m := _RE_CONST_SKIP.match(line):
            arg = _strip_comments(m.group(1))
            n = _eval_value(arg, syms | equs) if arg else 1
            counter += inc * (n if n is not None else 1)
            syms["const_value"] = counter
            continue

        if m := _RE_CONST_NEXT.match(line):
            v = _eval_value(m.group(1), syms | equs)
            if v is None:
                raise ValueError(f"cannot evaluate {line.strip()!r}")
            if v < counter:
                raise ValueError(f"const_next goes backwards from {counter} to {v}")
            counter = v
            syms["const_value"] = counter
            continue

        if m := _RE_EQU.match(line):
            name, val = m.group(1), m.group(2)
            v = _eval_value(val, syms | equs)
            if v is not None:
                equs[name] = v
            continue

        if m := _RE_CHARMAP.match(line):
            name, val = m.group(1), m.group(2)
            v = _eval_value(val, syms | equs)
            if v is not None:
                syms[name] = v

    syms.pop("const_value", None)
    if not aliases:
        return syms
    return syms | {k: v for k, v in equs.items() if k not in syms}


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
    print(parse_asm_constants(Path("constants/map_constants.asm").read_text()))
