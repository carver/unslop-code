#!/usr/bin/env python3
"""Command line entry point for the sith code intelligence tool."""

import argparse
import sys
from pathlib import Path

from sithlib.configuration import initialize, load_config
from sithlib.definitions import document
from sithlib.engine import complete
from sithlib.environments import details, installations, listing, virtualenvs
from sithlib.extraction import extract_function, extract_variable
from sithlib.inlining import inline
from sithlib.listing import names, search
from sithlib.namespaces import Namespaces, load_namespaces
from sithlib.navigation import goto, infer
from sithlib.project import Project
from sithlib.references import FILE, PROJECT, references
from sithlib.renaming import rename
from sithlib.scopes import context
from sithlib.settings import parse_settings
from sithlib.signatures import signatures
from sithlib.syntax import syntax_errors
from sithlib.source import Source, SourceError

SEPARATOR = ","


class Parser(argparse.ArgumentParser):
    """Argument parser that reports usage errors with the tool's exit code."""

    def error(self, message):
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> Parser:
    parser = Parser(prog="sith", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = analysed(commands, "complete", "suggest completions at a cursor position")
    completion.add_argument("--fuzzy", action="store_true", help="match prefixes as subsequences")
    analysed(commands, "infer", "report what the name at the cursor evaluates to")
    navigation = analysed(commands, "goto", "report where the name at the cursor was defined")
    navigation.add_argument(
        "--follow-imports", action="store_true", help="answer in the module an import came from"
    )
    analysed(commands, "signatures", "describe the call the cursor is writing arguments for")
    finding = at_cursor(commands, "references", "find where the name at the cursor is written")
    finding.add_argument(
        "--scope", choices=(FILE, PROJECT), default=FILE, help="how far the search reaches"
    )
    at_cursor(commands, "context", "report the scopes the cursor is written inside")
    listing = in_project(subcommand(commands, "names", "list the names a file defines"))
    listing.add_argument("file", help="Python source file to analyse")
    listing.add_argument(
        "--all-scopes", action="store_true", help="include names defined inside other scopes"
    )
    query = in_project(subcommand(commands, "search", "find definitions across the project"))
    query.add_argument("query", help="text a definition's name must contain")
    renaming = with_diff(at_cursor(commands, "rename", "rename a name across the project"))
    renaming.add_argument("--new-name", required=True, help="the name to give it")
    with_diff(at_cursor(commands, "inline", "replace a variable with its value"))
    extraction(commands, "extract-variable", "name an expression and use the name instead")
    extraction(commands, "extract-function", "move statements into a function of their own")
    subcommand(commands, "errors", "report the syntax errors in a file").add_argument(
        "file", help="Python source file to analyse"
    )
    environment_commands(commands)
    project_commands(commands)
    return parser


def subcommand(commands, name: str, help: str):
    """Add a subcommand, with the settings flag every command accepts."""
    command = commands.add_parser(name, help=help)
    command.add_argument(
        "--setting", action="append", default=[], metavar="KEY=VALUE",
        help="override a default behaviour, written as key=value",
    )
    command.set_defaults(project=None, interpreter=False, namespaces=None)
    return command


def with_diff(command):
    """Add the option that asks for a unified diff instead of file contents."""
    command.add_argument(
        "--diff", action="store_true", help="write a unified diff instead of JSON"
    )
    return command


def extraction(commands, name: str, help: str):
    """Add a subcommand extracting the code a selection covers."""
    command = with_diff(at_cursor(commands, name, help))
    command.add_argument(
        "--until", required=True, type=position, help="end of the selection, as line:col"
    )
    command.add_argument("--name", required=True, help="name for the extracted code")
    return command


def position(text: str):
    """A ``line:col`` option, as the pair of numbers it writes."""
    line, _, column = text.partition(":")
    return int(line), int(column)


def in_project(command):
    """Add the project root option every subcommand accepts."""
    command.add_argument("--project", help="project root; defaults to the directory holding <file>")
    return command


def at_cursor(commands, name: str, help: str):
    """Add a subcommand taking a source file and a cursor position."""
    command = subcommand(commands, name, help)
    command.add_argument("file", help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    return in_project(command)


def analysed(commands, name: str, help: str):
    """Add an analysis subcommand, which may run against live namespaces."""
    command = at_cursor(commands, name, help)
    command.add_argument(
        "--interpreter", action="store_true", help="fall back to a running interpreter's names"
    )
    command.add_argument("--namespaces", help="JSON file describing the interpreter's namespaces")
    return command


def environment_commands(commands):
    """Add the read-only `env` discovery subcommands."""
    found = commands.add_parser("env", help="inspect the Python environments available")
    actions = found.add_subparsers(dest="action", required=True)
    in_project(subcommand(actions, "list", "list the Python installations found"))
    searched = in_project(subcommand(actions, "find-virtualenvs", "list the virtualenvs found"))
    searched.add_argument("--path", help="directory whose subdirectories hold virtualenvs")
    described = in_project(subcommand(actions, "info", "describe one Python environment"))
    described.add_argument("executable", nargs="?", help="interpreter to describe")


def project_commands(commands):
    """Add the subcommands that write project configuration."""
    configuration = commands.add_parser("project", help="configure a project")
    actions = configuration.add_subparsers(dest="action", required=True)
    written = subcommand(actions, "init", "create or update a project configuration")
    written.add_argument("dir", nargs="?", help="project root; defaults to the current directory")
    written.add_argument("--environment", help="Python executable the project is analysed with")
    written.add_argument("--sys-path", help="import roots replacing the detected ones")
    written.add_argument("--added-sys-path", help="import roots added to the detected ones")


def answer(arguments) -> str:
    """The JSON document a parsed command line asks for."""
    overrides = parse_settings(arguments.setting)
    if arguments.command == "env":
        return environment_answer(arguments)
    if arguments.command == "project":
        return document(**initialize(arguments.dir or Path.cwd(), configured(arguments)))
    if arguments.command == "search":
        return search(project_at(Path.cwd(), arguments, overrides), arguments.query)
    source = Source.load(arguments.file)
    if arguments.command == "errors":
        return syntax_errors(source)
    project = project_at(source.path.parent, arguments, overrides)
    return ANSWERS[arguments.command](arguments, source, project)


def project_at(default_root, arguments, overrides) -> Project:
    """The project a command runs in, with its configuration and settings."""
    root = arguments.project or default_root
    return Project(root, overrides, interpreter_namespaces(arguments))


def interpreter_namespaces(arguments) -> Namespaces:
    """The namespaces interpreter mode was given, if it was given any."""
    if arguments.namespaces is None:
        return Namespaces()
    if not arguments.interpreter:
        raise SourceError("--namespaces requires --interpreter")
    return load_namespaces(arguments.namespaces)


def environment_answer(arguments) -> str:
    """The answer of an `env` subcommand."""
    root = Path(arguments.project or Path.cwd())
    if arguments.action == "info":
        return details(arguments.executable or load_config(root).environment_path)
    found = installations(root) if arguments.action == "list" else virtualenvs(arguments.path, root)
    return listing(found)


def configured(arguments) -> dict:
    """The configuration fields `project init` was asked to write."""
    written = {}
    if arguments.environment is not None:
        written["environment_path"] = arguments.environment
    if arguments.sys_path is not None:
        written["sys_path"] = entries(arguments.sys_path)
    if arguments.added_sys_path is not None:
        written["added_sys_path"] = entries(arguments.added_sys_path)
    return written


def entries(written: str) -> list:
    """The paths a comma separated list of import roots names."""
    return [entry for entry in written.split(SEPARATOR) if entry]


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
    "context": lambda given, source, project: context(source, project, given.line, given.col),
    "names": lambda given, source, project: names(source, project, given.all_scopes),
    "rename": lambda given, source, project: rename(
        source, project, given.line, given.col, given.new_name, given.diff
    ),
    "inline": lambda given, source, project: inline(
        source, project, given.line, given.col, given.diff
    ),
    "extract-variable": lambda given, source, project: extract_variable(
        source, project, given.line, given.col, given.until, given.name, given.diff
    ),
    "extract-function": lambda given, source, project: extract_function(
        source, project, given.line, given.col, given.until, given.name, given.diff
    ),
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
