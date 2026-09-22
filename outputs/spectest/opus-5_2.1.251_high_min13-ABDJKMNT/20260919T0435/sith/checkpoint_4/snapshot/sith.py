#!/usr/bin/env python3
"""Command-line Python code intelligence.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.navigate import goto, infer
from sithlib.references import references
from sithlib.search import names, search
from sithlib.signatures import signatures
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
    _cursor_command(commands, "signatures", "the signature of the call at the cursor")
    used = _cursor_command(commands, "references", "everywhere the name at the cursor appears")
    used.add_argument(
        "--scope", choices=["file", "project"], default="file", help="how far to search"
    )
    query = _project_command(commands, "search", "definitions whose name matches a query")
    query.add_argument("query", help="text a definition's name must contain")
    listing = _project_command(commands, "names", "the names a file defines")
    listing.add_argument("file", help="Python source file to analyse")
    listing.add_argument(
        "--all-scopes", action="store_true", help="include locals, attributes and nested defs"
    )
    return parser


def _cursor_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    command = _project_command(commands, name, help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based line number")
    command.add_argument("col", type=int, help="0-based column number")
    return command


def _project_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    command = commands.add_parser(name, help=help)
    command.add_argument("--project", help="project root; defaults to the file's directory")
    return command


#: The payload each subcommand answers with, keyed by the name it is invoked as.
ANSWERS = {
    "complete": lambda a: {"completions": complete(a.file, a.line, a.col, a.fuzzy, a.project)},
    "infer": lambda a: {"definitions": infer(a.file, a.line, a.col, a.project)},
    "goto": lambda a: {"definitions": goto(a.file, a.line, a.col, a.project, a.follow_imports)},
    "signatures": lambda a: {"signatures": signatures(a.file, a.line, a.col, a.project)},
    "references": lambda a: {"references": references(a.file, a.line, a.col, a.scope, a.project)},
    "search": lambda a: {"definitions": search(a.query, a.project)},
    "names": lambda a: {"definitions": names(a.file, a.all_scopes, a.project)},
}


def answer(arguments: argparse.Namespace) -> dict:
    """The JSON payload of one request."""
    return ANSWERS[arguments.command](arguments)


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
