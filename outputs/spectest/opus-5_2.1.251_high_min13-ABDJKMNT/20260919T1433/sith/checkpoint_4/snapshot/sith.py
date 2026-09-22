#!/usr/bin/env python3
"""Command line entry point for the sith code intelligence tool."""

import argparse
import sys
from pathlib import Path

from sithlib.engine import complete
from sithlib.listing import names, search
from sithlib.navigation import goto, infer
from sithlib.project import Project
from sithlib.references import FILE, PROJECT, references
from sithlib.signatures import signatures
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
    at_cursor(commands, "signatures", "describe the call the cursor is writing arguments for")
    finding = at_cursor(commands, "references", "find where the name at the cursor is written")
    finding.add_argument(
        "--scope", choices=(FILE, PROJECT), default=FILE, help="how far the search reaches"
    )
    listing = in_project(commands.add_parser("names", help="list the names a file defines"))
    listing.add_argument("file", help="Python source file to analyse")
    listing.add_argument(
        "--all-scopes", action="store_true", help="include names defined inside other scopes"
    )
    query = in_project(commands.add_parser("search", help="find definitions across the project"))
    query.add_argument("query", help="text a definition's name must contain")
    return parser


def in_project(command):
    """Add the project root option every subcommand accepts."""
    command.add_argument("--project", help="project root; defaults to the directory holding <file>")
    return command


def at_cursor(commands, name: str, help: str):
    """Add a subcommand taking a source file and a cursor position."""
    command = commands.add_parser(name, help=help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    return in_project(command)


def answer(arguments) -> str:
    """The JSON document a parsed command line asks for."""
    if arguments.command == "search":
        return search(Project(arguments.project or Path.cwd()), arguments.query)
    source = Source.load(arguments.file)
    project = Project(arguments.project or source.path.parent)
    return ANSWERS[arguments.command](arguments, source, project)


ANSWERS = {
    "complete": lambda given, source, project: complete(
        source, project, given.line, given.col, given.fuzzy
    ),
    "infer": lambda given, source, project: infer(source, project, given.line, given.col),
    "goto": lambda given, source, project: goto(
        source, project, given.line, given.col, given.follow_imports
    ),
    "signatures": lambda given, source, project: signatures(
        source, project, given.line, given.col
    ),
    "references": lambda given, source, project: references(
        source, project, given.line, given.col, given.scope
    ),
    "names": lambda given, source, project: names(source, project, given.all_scopes),
}


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        output = answer(arguments)
    except SourceError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
