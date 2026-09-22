#!/usr/bin/env python3
"""Command-line Python code intelligence.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.navigate import goto, infer
from sithlib.source import SithError


class Parser(argparse.ArgumentParser):
    """Reports usage problems the same way as any other error: STDERR, exit 1."""

    def error(self, message: str):
        self.exit(1, f"{self.prog}: {message}\n")


def build_parser() -> Parser:
    parser = Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _cursor_command(commands, "complete", "complete at a cursor position")
    completion.add_argument(
        "--fuzzy", action="store_true", help="match prefix characters in order, not contiguously"
    )
    _cursor_command(commands, "infer", "what the name at the cursor evaluates to")
    navigation = _cursor_command(commands, "goto", "where the name at the cursor is defined")
    navigation.add_argument(
        "--follow-imports", action="store_true", help="chase imports into the defining module"
    )
    return parser


def _cursor_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    command = commands.add_parser(name, help=help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based line number")
    command.add_argument("col", type=int, help="0-based column number")
    command.add_argument("--project", help="project root; defaults to the file's directory")
    return command


def answer(arguments: argparse.Namespace) -> dict:
    """The JSON payload of one request."""
    position = (arguments.file, arguments.line, arguments.col)
    if arguments.command == "complete":
        return {"completions": complete(*position, arguments.fuzzy, arguments.project)}
    if arguments.command == "infer":
        return {"definitions": infer(*position, arguments.project)}
    return {"definitions": goto(*position, arguments.project, arguments.follow_imports)}


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        payload = answer(arguments)
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
