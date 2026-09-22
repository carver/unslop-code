#!/usr/bin/env python3
"""Command-line Python code intelligence: completions at a cursor position.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]
"""

from __future__ import annotations

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.source import SithError


class Parser(argparse.ArgumentParser):
    """Reports usage problems the same way as any other error: STDERR, exit 1."""

    def error(self, message: str):
        self.exit(1, f"{self.prog}: {message}\n")


def build_parser() -> Parser:
    parser = Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    complete_command = commands.add_parser("complete", help="complete at a cursor position")
    complete_command.add_argument("file", help="Python source file to analyse")
    complete_command.add_argument("line", type=int, help="1-based line number")
    complete_command.add_argument("col", type=int, help="0-based column number")
    complete_command.add_argument(
        "--fuzzy", action="store_true", help="match prefix characters in order, not contiguously"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        completions = complete(arguments.file, arguments.line, arguments.col, arguments.fuzzy)
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    payload = json.dumps({"completions": completions}, separators=(",", ":"))
    sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
