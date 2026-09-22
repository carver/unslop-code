"""The command line: the subcommands and flags every command accepts."""

import argparse
import sys

from .references import FILE, PROJECT


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the tool's exit code."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.exit(f"sith: {message}")


def build_parser(description):
    """The parser for the whole tool, one subparser per command."""
    parser = _Parser(prog="sith", description=description)
    parser.set_defaults(file=None, project=None, directory=None, setting=None,
                        interpreter=False, namespaces=None)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _interpreted(commands, "complete", "suggest completions at a cursor")
    completion.add_argument(
        "--fuzzy",
        action="store_true",
        help="match prefix characters in order instead of contiguously",
    )
    inference = _interpreted(commands, "infer", "describe what the name at a cursor evaluates to")
    _dynamic(inference)
    navigation = _interpreted(commands, "goto", "describe where the name at a cursor is defined")
    navigation.add_argument(
        "--follow-imports",
        action="store_true",
        help="report the definition an import leads to instead of the import itself",
    )
    signature = _interpreted(commands, "signatures", "describe the call the cursor sits in")
    _dynamic(signature)
    reference = _cursor(commands, "references", "list where the name at a cursor is used")
    reference.add_argument(
        "--scope",
        choices=(FILE, PROJECT),
        default=FILE,
        help="search the cursor's file only, or every file of the project",
    )
    _cursor(commands, "context", "list the scopes a cursor sits inside")
    finder = _command(commands, "search", "list the project definitions matching a name")
    finder.add_argument("query", help="substring the definition names must hold")
    _project(finder)
    listing = _command(commands, "names", "list the names a file defines")
    listing.add_argument("file", help="path to the Python source file")
    listing.add_argument(
        "--all-scopes",
        action="store_true",
        help="include the names defined inside functions and classes",
    )
    _project(listing)
    report = _command(commands, "errors", "list the syntax errors a file holds")
    report.add_argument("file", help="path to the Python source file")
    renaming = _refactoring(commands, "rename", "rename the name at a cursor everywhere")
    renaming.add_argument("--new-name", required=True, help="the name to rename it to")
    _refactoring(commands, "inline", "replace a variable by the value it holds")
    _selection(commands, "extract-variable", "name the selected expression")
    _selection(commands, "extract-function", "move the selected statements into a function")
    _environments(commands)
    _configuration(commands)
    return parser


def project_updates(arguments):
    """The project-file fields `project init` was asked to change, and no others."""
    given = (
        ("environment_path", arguments.environment),
        ("sys_path", _split(arguments.sys_path)),
        ("added_sys_path", _split(arguments.added_sys_path)),
    )
    return {name: value for name, value in given if value is not None}


def _command(commands, name, help_text):
    """Add a subcommand, which may always be given settings to run under."""
    command = commands.add_parser(name, help=help_text)
    command.add_argument(
        "--setting",
        action="append",
        metavar="KEY=VALUE",
        help="override one setting, such as case_insensitive=false",
    )
    return command


def _cursor(commands, name, help_text):
    """Add a subcommand taking the file and cursor position a cursor command needs."""
    command = _command(commands, name, help_text)
    command.add_argument("file", help="path to the Python source file")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    _project(command)
    return command


def _interpreted(commands, name, help_text):
    """Add a cursor command that a running interpreter can answer for."""
    command = _cursor(commands, name, help_text)
    command.add_argument(
        "--interpreter",
        action="store_true",
        help="fall back to the names a running interpreter holds",
    )
    command.add_argument(
        "--namespaces",
        help="path to the JSON file describing those namespaces",
    )
    return command


def _refactoring(commands, name, help_text):
    """Add a subcommand rewriting source, which may print its edits as a diff."""
    command = _cursor(commands, name, help_text)
    command.add_argument(
        "--diff",
        action="store_true",
        help="print a unified diff instead of the new contents of each file",
    )
    return command


def _selection(commands, name, help_text):
    """Add a refactoring working on the region between the cursor and `--until`."""
    command = _refactoring(commands, name, help_text)
    command.add_argument("--until", required=True, help="end of the selection, as <line>:<col>")
    command.add_argument("--name", required=True, help="name of what the selection becomes")
    return command


def _environments(commands):
    """Add the `env` command, which discovers the interpreters of the machine."""
    environment = commands.add_parser("env", help="list the Python environments available")
    inside = environment.add_subparsers(dest="env_command", required=True)
    _project(_command(inside, "list", "list every Python installation found"))
    virtualenvs = _command(inside, "find-virtualenvs", "list the virtualenvs found")
    virtualenvs.add_argument("--path", help="a directory whose subdirectories are virtualenvs")
    _project(virtualenvs)
    information = _command(inside, "info", "describe one Python environment")
    information.add_argument("executable", nargs="?",
                             help="the interpreter to describe; defaults to the project's")
    _project(information)


def _configuration(commands):
    """Add the `project` command, which writes the project file."""
    configuration = commands.add_parser("project", help="read and write the project file")
    inside = configuration.add_subparsers(dest="project_command", required=True)
    initialisation = _command(inside, "init", "create or update the project file")
    initialisation.add_argument("directory", nargs="?",
                                help="project root; defaults to the working directory")
    initialisation.add_argument("--environment", help="path to the interpreter the project uses")
    initialisation.add_argument("--sys-path", help="comma-separated import roots, replacing "
                                                   "the detected ones")
    initialisation.add_argument("--added-sys-path",
                                help="comma-separated import roots to add to them")


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


def _split(text):
    """The paths of a comma-separated list, or ``None`` when none was given."""
    if text is None:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]
