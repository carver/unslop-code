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
    python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
    python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
    python sith.py extract-variable <file> <line> <col> --until <line>:<col>
        --name <name> [--diff] [--project <dir>]
    python sith.py extract-function <file> <line> <col> --until <line>:<col>
        --name <name> [--diff] [--project <dir>]
    python sith.py errors <file>
    python sith.py context <file> <line> <col> [--project <dir>]
    python sith.py env list
    python sith.py env find-virtualenvs [--path <dir>]
    python sith.py env info [<executable>]
    python sith.py project init [<dir>] [--environment <executable>]
        [--sys-path <path>[,...]] [--added-sys-path <path>[,...]]

The analysis commands take `--interpreter --namespaces <file>` to fall back on
the values of a live session, and every command takes `--setting key=value`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from sithlib import config, environments
from sithlib.context import context
from sithlib.diagnostics import errors
from sithlib.engine import complete
from sithlib.extract import extract_function, extract_variable
from sithlib.inline import inline
from sithlib.navigate import goto, infer
from sithlib.options import Options
from sithlib.references import references
from sithlib.rename import rename
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
    completion = _analysis_command(commands, "complete", "complete at a cursor position")
    completion.add_argument(
        "--fuzzy", action="store_true", help="match prefix characters in order, not contiguously"
    )
    _analysis_command(commands, "infer", "what the name at the cursor evaluates to")
    navigation = _analysis_command(commands, "goto", "where the name at the cursor is defined")
    navigation.add_argument(
        "--follow-imports", action="store_true", help="chase imports into the defining module"
    )
    _analysis_command(commands, "signatures", "the signature of the call at the cursor")
    _cursor_command(commands, "context", "the scopes the cursor is written inside")
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
    renaming = _edit_command(commands, "rename", "rename the name at the cursor everywhere")
    renaming.add_argument("--new-name", required=True, help="what the name becomes")
    _edit_command(commands, "inline", "replace a variable with the value it holds")
    _selection_command(commands, "extract-variable", "name the selected expression")
    _selection_command(commands, "extract-function", "move the selected statements out")
    reporting = _command(commands, "errors", "the syntax errors of a file")
    reporting.add_argument("file", help="Python source file to analyse")
    _environment_commands(commands)
    _configuration_commands(commands)
    return parser


def _environment_commands(commands) -> None:
    """`env`: read-only discovery of the Python installations of this machine."""
    group = commands.add_parser("env", help="the Python environments available here")
    actions = group.add_subparsers(dest="action", required=True)
    _project_command(actions, "list", "every Python installation found")
    searching = _project_command(actions, "find-virtualenvs", "the virtualenvs of the usual places")
    searching.add_argument("--path", help="a directory whose subdirectories are virtualenvs")
    details = _project_command(actions, "info", "everything one environment knows about itself")
    details.add_argument("executable", nargs="?", help="the interpreter to describe")


def _configuration_commands(commands) -> None:
    """`project`: the only command that writes the project configuration file."""
    group = commands.add_parser("project", help="the project configuration file")
    actions = group.add_subparsers(dest="action", required=True)
    initialising = _command(actions, "init", "create or update `.sith/project.json`")
    initialising.add_argument("dir", nargs="?", help="project directory; defaults to the cwd")
    initialising.add_argument("--environment", help="the Python executable of the project")
    initialising.add_argument("--sys-path", help="comma-separated import roots")
    initialising.add_argument("--added-sys-path", help="comma-separated extra import roots")


def _cursor_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    command = _project_command(commands, name, help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based line number")
    command.add_argument("col", type=int, help="0-based column number")
    return command


def _analysis_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    """A cursor command that may fall back on the namespaces of a live session."""
    command = _cursor_command(commands, name, help)
    command.add_argument(
        "--interpreter", action="store_true", help="fall back on live namespaces"
    )
    command.add_argument("--namespaces", help="JSON file describing the live namespaces")
    return command


def _edit_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    """A refactoring: a cursor, and a choice of how the edits are reported."""
    command = _cursor_command(commands, name, help)
    command.add_argument(
        "--diff", action="store_true", help="report a unified diff instead of JSON"
    )
    return command


def _selection_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    """A refactoring driven by a selected region rather than by a cursor alone."""
    command = _edit_command(commands, name, help)
    command.add_argument(
        "--until", required=True, type=_position, help="end of the selection, as line:col"
    )
    command.add_argument("--name", required=True, help="what the extracted code is called")
    return command


def _position(text: str) -> tuple[int, int]:
    """A `line:col` position as written on the command line."""
    line, _, column = text.partition(":")
    return int(line), int(column)


def _command(commands, name: str, help: str) -> argparse.ArgumentParser:
    """Any subcommand, with the setting overrides they all accept."""
    command = commands.add_parser(name, help=help)
    command.add_argument(
        "--setting", action="append", default=[], metavar="KEY=VALUE",
        help="override a default, written as `key=value`",
    )
    return command


def _project_command(commands, name: str, help: str) -> argparse.ArgumentParser:
    command = _command(commands, name, help)
    command.add_argument("--project", help="project root; defaults to the file's directory")
    return command


#: The payload each subcommand answers with, keyed by the name it is invoked as.
ANSWERS = {
    "complete": lambda a, o: {
        "completions": complete(a.file, a.line, a.col, a.fuzzy, a.project, o)
    },
    "infer": lambda a, o: {"definitions": infer(a.file, a.line, a.col, a.project, o)},
    "goto": lambda a, o: {
        "definitions": goto(a.file, a.line, a.col, a.project, a.follow_imports, o)
    },
    "signatures": lambda a, o: {"signatures": signatures(a.file, a.line, a.col, a.project, o)},
    "context": lambda a, o: {"context": context(a.file, a.line, a.col, a.project, o)},
    "references": lambda a, o: {
        "references": references(a.file, a.line, a.col, a.scope, a.project, o)
    },
    "search": lambda a, o: {"definitions": search(a.query, a.project, o)},
    "names": lambda a, o: {"definitions": names(a.file, a.all_scopes, a.project, o)},
    "rename": lambda a, o: rename(a.file, a.line, a.col, a.new_name, a.project, a.diff, o),
    "inline": lambda a, o: inline(a.file, a.line, a.col, a.project, a.diff, o),
    "extract-variable": lambda a, o: extract_variable(
        a.file, a.line, a.col, a.until, a.name, a.project, a.diff
    ),
    "extract-function": lambda a, o: extract_function(
        a.file, a.line, a.col, a.until, a.name, a.project, a.diff
    ),
    "errors": lambda a, o: {"errors": errors(a.file)},
    "env list": lambda a, o: {"environments": environments.installed(_root(a))},
    "env find-virtualenvs": lambda a, o: {
        "environments": environments.virtualenvs(a.path, _root(a))
    },
    "env info": lambda a, o: {
        "environment": environments.details(a.executable or o.at(_root(a)).config.environment_path)
    },
    "project init": lambda a, o: {
        "project": config.initialize(a.dir, a.environment, a.sys_path, a.added_sys_path)
    },
}


def _root(arguments: argparse.Namespace) -> str:
    """The project root of a command that names no file of its own."""
    return os.path.abspath(arguments.project or os.curdir)


def _invoked(arguments: argparse.Namespace) -> str:
    """How a command was named, `env list` and `project init` included."""
    action = getattr(arguments, "action", None)
    return f"{arguments.command} {action}" if action else arguments.command


def answer(arguments: argparse.Namespace) -> dict | str:
    """The payload of one request: a JSON object, or the text of a diff."""
    options = Options.of(arguments)
    return ANSWERS[_invoked(arguments)](arguments, options)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        payload = answer(arguments)
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    if isinstance(payload, str):
        sys.stdout.write(payload)
    else:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
