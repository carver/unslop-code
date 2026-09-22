#!/usr/bin/env python3
"""Command line entry point for the sith code intelligence tool."""

import argparse
import sys
from pathlib import Path

from sithlib.engine import complete
from sithlib.navigation import goto, infer
from sithlib.project import Project
from sithlib.source import Source, SourceError


class Parser(argparse.ArgumentParser):
    """Argument parser that reports usage errors with the tool's exit code."""

    def error(self, message):
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> Parser:
    parser = Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = at_cursor(commands, "complete", "suggest completions at a cursor position")
    completion.add_argument("--fuzzy", action="store_true", help="match prefixes as subsequences")
    at_cursor(commands, "infer", "report what the name at the cursor evaluates to")
    navigation = at_cursor(commands, "goto", "report where the name at the cursor was defined")
    navigation.add_argument(
        "--follow-imports", action="store_true", help="answer in the module an import came from"
    )
    return parser


def at_cursor(commands, name: str, help: str):
    """Add a subcommand taking a source file and a cursor position."""
    command = commands.add_parser(name, help=help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    command.add_argument(
        "--project", help="project root; defaults to the directory holding <file>"
    )
    return command


def answer(arguments, source: Source, project: Project) -> str:
    """The JSON document a parsed command line asks for."""
    if arguments.command == "complete":
        return complete(source, project, arguments.line, arguments.col, arguments.fuzzy)
    if arguments.command == "goto":
        return goto(source, project, arguments.line, arguments.col, arguments.follow_imports)
    return infer(source, project, arguments.line, arguments.col)


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        source = Source.load(arguments.file)
        root = Path(arguments.project) if arguments.project else source.path.parent
        output = answer(arguments, source, Project(root))
    except SourceError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
