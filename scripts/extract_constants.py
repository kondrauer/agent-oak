"""Regenerate data/constants.json from the pokered sources.

Usage: uv run python scripts/extract_constants.py [--pokered PATH]
"""

import argparse
from pathlib import Path

from agent_oak.objectives.constants import CONSTANTS_PATH, write_constants

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate data/constants.json from the pokered sources."
    )
    parser.add_argument(
        "--pokered",
        type=Path,
        default=Path("."),
        help="pokered checkout to read, defaults to the files vendored in the repo",
    )
    parser.add_argument("--out", type=Path, default=CONSTANTS_PATH)
    args = parser.parse_args()
    write_constants(root=args.pokered, out=args.out)
    print(f"Wrote {args.out}")
