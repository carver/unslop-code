#!/usr/bin/env python3
"""Command-line code intelligence for Python sources.

    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--no-dynamic] [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--no-dynamic] [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]

Imports are resolved inside the project, whose root defaults to the directory
holding <file>, and type information comes from a `.pyi` stub when the project
ships one. Prints a JSON object to STDOUT holding a "completions",
"definitions", "signatures" or "references" array.
"""

import argparse
import json
import sys

from sithlib.engine import complete
from sithlib.errors import SithError
from sithlib.navigation import goto, infer
from sithlib.references import FILE, PROJECT, references
from sithlib.search import names, search
from sithlib.signatures import signatures


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the tool's exit code."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.exit(f"sith: {message}")


_COMMANDS = {
    "complete": lambda args: (
        "completions",
        complete(args.file, args.line, args.col, args.fuzzy, args.project),
    ),
    "infer": lambda args: (
        "definitions",
        infer(args.file, args.line, args.col, args.project, not args.no_dynamic),
    ),
    "goto": lambda args: (
        "definitions",
        goto(args.file, args.line, args.col, args.follow_imports, args.project),
    ),
    "signatures": lambda args: (
        "signatures",
        signatures(args.file, args.line, args.col, not args.no_dynamic, args.project),
    ),
    "references": lambda args: (
        "references",
        references(args.file, args.line, args.col, args.scope, args.project),
    ),
    "search": lambda args: ("definitions", search(args.query, args.project)),
    "names": lambda args: ("definitions", names(args.file, args.all_scopes, args.project)),
}


def _build_parser():
    parser = _Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _cursor(commands, "complete", "suggest completions at a cursor")
    completion.add_argument(
        "--fuzzy",
        action="store_true",
        help="match prefix characters in order instead of contiguously",
    )
    inference = _cursor(commands, "infer", "describe what the name at a cursor evaluates to")
    _dynamic(inference)
    navigation = _cursor(commands, "goto", "describe where the name at a cursor is defined")
    navigation.add_argument(
        "--follow-imports",
        action="store_true",
        help="report the definition an import leads to instead of the import itself",
    )
    signature = _cursor(commands, "signatures", "describe the call the cursor sits in")
    _dynamic(signature)
    reference = _cursor(commands, "references", "list where the name at a cursor is used")
    reference.add_argument(
        "--scope",
        choices=(FILE, PROJECT),
        default=FILE,
        help="search the cursor's file only, or every file of the project",
    )
    finder = commands.add_parser("search", help="list the project definitions matching a name")
    finder.add_argument("query", help="substring the definition names must hold")
    _project(finder)
    listing = commands.add_parser("names", help="list the names a file defines")
    listing.add_argument("file", help="path to the Python source file")
    listing.add_argument(
        "--all-scopes",
        action="store_true",
        help="include the names defined inside functions and classes",
    )
    _project(listing)
    return parser


def _cursor(commands, name, help_text):
    """Add a subcommand taking the file and cursor position a cursor command needs."""
    command = commands.add_parser(name, help=help_text)
    command.add_argument("file", help="path to the Python source file")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    _project(command)
    return command


def _project(command):
    command.add_argument(
        "--project",
        help="root directory imports are resolved against; defaults to the file's directory",
    )


def _dynamic(command):
    command.add_argument(
        "--no-dynamic",
        action="store_true",
        help="leave an unannotated parameter untyped instead of reading its call sites",
    )


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
