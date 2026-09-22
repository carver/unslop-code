#!/usr/bin/env python3
"""Command-line code intelligence for Python sources.

    python sith.py complete <file> <line> <col> [--fuzzy]

Prints a JSON object with a "completions" array to STDOUT.
"""

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.errors import SithError


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the tool's exit code."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.exit(f"sith: {message}")


def _build_parser():
    parser = _Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = commands.add_parser("complete", help="suggest completions at a cursor")
    completion.add_argument("file", help="path to the Python source file")
    completion.add_argument("line", type=int, help="1-based cursor line")
    completion.add_argument("col", type=int, help="0-based cursor column")
    completion.add_argument(
        "--fuzzy",
        action="store_true",
        help="match prefix characters in order instead of contiguously",
    )
    return parser


def main(argv=None):
    arguments = _build_parser().parse_args(argv)
    try:
        completions = complete(arguments.file, arguments.line, arguments.col, arguments.fuzzy)
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    json.dump({"completions": completions}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
