"""Command line entry point for the sith code intelligence tool.

    python sith.py complete <file> <line> <col> [--fuzzy]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sithlib.engine import complete
from sithlib.errors import SithError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sith.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = commands.add_parser("complete", help="suggest completions at a cursor position")
    completion.add_argument("file", type=Path, help="Python source file to analyse")
    completion.add_argument("line", type=int, help="1-based cursor line")
    completion.add_argument("col", type=int, help="0-based cursor column")
    completion.add_argument("--fuzzy", action="store_true",
                            help="match prefix characters in order rather than contiguously")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        completions = complete(arguments.file, arguments.line, arguments.col, arguments.fuzzy)
    except SithError as error:
        print(error, file=sys.stderr)
        return 1
    payload = {"completions": [completion.as_dict() for completion in completions]}
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
