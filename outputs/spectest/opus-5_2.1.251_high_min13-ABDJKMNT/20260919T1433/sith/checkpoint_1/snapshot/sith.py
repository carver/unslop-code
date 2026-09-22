#!/usr/bin/env python3
"""Command line entry point for the sith code intelligence tool."""

import argparse
import sys

from sithlib.engine import complete
from sithlib.source import Source, SourceError


class Parser(argparse.ArgumentParser):
    """Argument parser that reports usage errors with the tool's exit code."""

    def error(self, message):
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> Parser:
    parser = Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = commands.add_parser("complete", help="suggest completions at a cursor position")
    completion.add_argument("file", help="Python source file to analyse")
    completion.add_argument("line", type=int, help="1-based cursor line")
    completion.add_argument("col", type=int, help="0-based cursor column")
    completion.add_argument("--fuzzy", action="store_true", help="match prefixes as subsequences")
    return parser


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        source = Source.load(arguments.file)
        output = complete(source, arguments.line, arguments.col, arguments.fuzzy)
    except SourceError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
