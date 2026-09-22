"""Command line entry point for the sith code intelligence tool.

    python sith.py complete <file> <line> <col> [--fuzzy]
    python sith.py infer <file> <line> <col>
    python sith.py goto <file> <line> <col>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sithlib import engine
from sithlib.errors import SithError

FINDERS = {"infer": engine.infer, "goto": engine.goto}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sith.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _position_command(commands, "complete",
                                   "suggest completions at a cursor position")
    completion.add_argument("--fuzzy", action="store_true",
                            help="match prefix characters in order rather than contiguously")
    _position_command(commands, "infer", "report what the name at a cursor evaluates to")
    _position_command(commands, "goto", "report where the name at a cursor is defined")
    return parser


def _position_command(commands: argparse._SubParsersAction, name: str,
                      help: str) -> argparse.ArgumentParser:
    command = commands.add_parser(name, help=help)
    command.add_argument("file", type=Path, help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        payload = _payload(arguments)
    except SithError as error:
        print(error, file=sys.stderr)
        return 1
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def _payload(arguments: argparse.Namespace) -> dict[str, list[dict[str, object]]]:
    """The JSON body of one request."""
    if arguments.command == "complete":
        completions = engine.complete(arguments.file, arguments.line, arguments.col,
                                      arguments.fuzzy)
        return {"completions": [completion.as_dict() for completion in completions]}
    found = FINDERS[arguments.command](arguments.file, arguments.line, arguments.col)
    return {"definitions": [definition.as_dict() for definition in found]}


if __name__ == "__main__":
    sys.exit(main())
