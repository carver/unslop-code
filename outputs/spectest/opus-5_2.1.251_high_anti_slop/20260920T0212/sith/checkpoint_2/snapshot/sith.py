#!/usr/bin/env python3
"""Command-line code intelligence for Python sources.

    python sith.py complete <file> <line> <col> [--fuzzy]
    python sith.py infer <file> <line> <col>
    python sith.py goto <file> <line> <col>

Prints a JSON object holding a "completions" or "definitions" array to STDOUT.
"""

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.errors import SithError
from sithlib.navigation import goto, infer


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the tool's exit code."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.exit(f"sith: {message}")


_COMMANDS = {
    "complete": lambda args: ("completions", complete(args.file, args.line, args.col, args.fuzzy)),
    "infer": lambda args: ("definitions", infer(args.file, args.line, args.col)),
    "goto": lambda args: ("definitions", goto(args.file, args.line, args.col)),
}


def _build_parser():
    parser = _Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _positional(commands, "complete", "suggest completions at a cursor")
    completion.add_argument(
        "--fuzzy",
        action="store_true",
        help="match prefix characters in order instead of contiguously",
    )
    _positional(commands, "infer", "describe what the name at a cursor evaluates to")
    _positional(commands, "goto", "describe where the name at a cursor is defined")
    return parser


def _positional(commands, name, help_text):
    """Add a subcommand taking the file and cursor position every command needs."""
    command = commands.add_parser(name, help=help_text)
    command.add_argument("file", help="path to the Python source file")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    return command


def main(argv=None):
    arguments = _build_parser().parse_args(argv)
    try:
        key, payload = _COMMANDS[arguments.command](arguments)
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    json.dump({key: payload}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
