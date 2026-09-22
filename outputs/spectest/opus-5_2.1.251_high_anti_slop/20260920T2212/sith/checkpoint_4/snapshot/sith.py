"""Command line entry point for the sith code intelligence tool.

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
from pathlib import Path

from sithlib import engine
from sithlib.errors import SithError

Payload = dict[str, list[dict[str, object]]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sith.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _position_command(commands, "complete",
                                   "suggest completions at a cursor position")
    completion.add_argument("--fuzzy", action="store_true",
                            help="match prefix characters in order rather than contiguously")
    _position_command(commands, "infer", "report what the name at a cursor evaluates to")
    navigation = _position_command(commands, "goto",
                                   "report where the name at a cursor is defined")
    navigation.add_argument("--follow-imports", action="store_true",
                            help="report the definition an imported name came from")
    _position_command(commands, "signatures",
                      "report the signatures of the call being written at a cursor")
    usage = _position_command(commands, "references",
                              "report where the name at a cursor is used")
    usage.add_argument("--scope", choices=("file", "project"), default="file",
                       help="search only the target file (default) or every project file")
    search = commands.add_parser("search", help="find project definitions by name")
    search.add_argument("query", help="substring to look for, case insensitively")
    search.add_argument("--project", type=Path, default=Path.cwd(),
                        help="project root to search (default: the working directory)")
    listing = commands.add_parser("names", help="list the names a file defines")
    listing.add_argument("file", type=Path, help="Python source file to analyse")
    listing.add_argument("--all-scopes", action="store_true",
                         help="include the names of nested scopes, not just module level ones")
    _project_option(listing)
    return parser


def _position_command(commands: argparse._SubParsersAction, name: str,
                      help: str) -> argparse.ArgumentParser:
    command = commands.add_parser(name, help=help)
    command.add_argument("file", type=Path, help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    _project_option(command)
    return command


def _project_option(command: argparse.ArgumentParser) -> None:
    command.add_argument("--project", type=Path, default=None,
                         help="project root (default: the directory holding the file)")


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        payload = _HANDLERS[arguments.command](arguments)
    except SithError as error:
        print(error, file=sys.stderr)
        return 1
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def _where(arguments: argparse.Namespace) -> tuple[Path, int, int, Path | None]:
    return arguments.file, arguments.line, arguments.col, arguments.project


def _complete(arguments: argparse.Namespace) -> Payload:
    found = engine.complete(*_where(arguments), fuzzy=arguments.fuzzy)
    return {"completions": [completion.as_dict() for completion in found]}


def _infer(arguments: argparse.Namespace) -> Payload:
    return {"definitions": [found.as_dict() for found in engine.infer(*_where(arguments))]}


def _goto(arguments: argparse.Namespace) -> Payload:
    found = engine.goto(*_where(arguments), follow=arguments.follow_imports)
    return {"definitions": [definition.as_dict() for definition in found]}


def _signatures(arguments: argparse.Namespace) -> Payload:
    found = engine.signatures(*_where(arguments))
    return {"signatures": [signature.as_dict() for signature in found]}


def _references(arguments: argparse.Namespace) -> Payload:
    found = engine.references(*_where(arguments), project_wide=arguments.scope == "project")
    return {"references": [occurrence.as_dict() for occurrence in found]}


def _search(arguments: argparse.Namespace) -> Payload:
    found = engine.search(arguments.query, arguments.project)
    return {"results": [definition.as_dict(docstring=False) for definition in found]}


def _names(arguments: argparse.Namespace) -> Payload:
    found = engine.names(arguments.file, arguments.project, all_scopes=arguments.all_scopes)
    return {"names": [{**definition.as_dict(), "is_definition": True} for definition in found]}


_HANDLERS = {"complete": _complete, "infer": _infer, "goto": _goto,
             "signatures": _signatures, "references": _references,
             "search": _search, "names": _names}


if __name__ == "__main__":
    sys.exit(main())
