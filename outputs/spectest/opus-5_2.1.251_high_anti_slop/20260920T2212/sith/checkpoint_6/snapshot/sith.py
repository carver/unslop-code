"""Command line entry point for the sith code intelligence tool.

    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--project <dir>]
    python sith.py context <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]
    python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
    python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
    python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>
                                    [--diff] [--project <dir>]
    python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>
                                    [--diff] [--project <dir>]
    python sith.py errors <file>
    python sith.py env list
    python sith.py env find-virtualenvs [--path <dir>]
    python sith.py env info [<executable>]
    python sith.py project init [<dir>] [--environment <executable>]
                                [--sys-path <path>[,...]] [--added-sys-path <path>[,...]]

Every command accepts ``--setting key=value``; ``complete``, ``infer``,
``goto`` and ``signatures`` accept ``--interpreter [--namespaces <file>]``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sithlib import engine, environments, options
from sithlib.config import ProjectConfig
from sithlib.edits import Refactoring
from sithlib.errors import SithError
from sithlib.namespaces import Namespaces
from sithlib.options import Options

Payload = dict[str, object] | str

# Options every command shares, and the ones interpreter mode adds.
_SETTINGS = argparse.ArgumentParser(add_help=False)
_SETTINGS.add_argument("--setting", dest="settings", action="append", default=[],
                       metavar="KEY=VALUE", help="override a default, as key=value")
_INTERPRETER = argparse.ArgumentParser(add_help=False)
_INTERPRETER.add_argument("--interpreter", action="store_true",
                          help="fall back to the live namespaces of a session")
_INTERPRETER.add_argument("--namespaces", type=Path,
                          help="JSON file describing the namespaces of a session")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sith.py", description=__doc__)
    parser.set_defaults(interpreter=False, namespaces=None)
    commands = parser.add_subparsers(dest="command", required=True)
    completion = _position_command(commands, "complete",
                                   "suggest completions at a cursor position", live=True)
    completion.add_argument("--fuzzy", action="store_true",
                            help="match prefix characters in order rather than contiguously")
    _position_command(commands, "infer", "report what the name at a cursor evaluates to",
                      live=True)
    navigation = _position_command(commands, "goto",
                                   "report where the name at a cursor is defined", live=True)
    navigation.add_argument("--follow-imports", action="store_true",
                            help="report the definition an imported name came from")
    _position_command(commands, "signatures",
                      "report the signatures of the call being written at a cursor", live=True)
    _position_command(commands, "context", "report the scopes a cursor is written inside")
    usage = _position_command(commands, "references",
                              "report where the name at a cursor is used")
    usage.add_argument("--scope", choices=("file", "project"), default="file",
                       help="search only the target file (default) or every project file")
    naming = _position_command(commands, "rename",
                               "rename the name at a cursor throughout the project")
    naming.add_argument("--new-name", required=True, help="the identifier to rename to")
    _diff_option(naming)
    _diff_option(_position_command(commands, "inline",
                                   "replace a variable with the value it was assigned"))
    _selection_command(commands, "extract-variable",
                       "extract the selected expression into a variable")
    _selection_command(commands, "extract-function",
                       "extract the selected statements into a function")
    broken = commands.add_parser("errors", help="report the syntax errors of a file",
                                 parents=[_SETTINGS])
    broken.add_argument("file", type=Path, help="Python source file to analyse")
    search = commands.add_parser("search", help="find project definitions by name",
                                 parents=[_SETTINGS])
    search.add_argument("query", help="substring to look for, case insensitively")
    search.add_argument("--project", type=Path, default=Path.cwd(),
                        help="project root to search (default: the working directory)")
    listing = commands.add_parser("names", help="list the names a file defines",
                                  parents=[_SETTINGS])
    listing.add_argument("file", type=Path, help="Python source file to analyse")
    listing.add_argument("--all-scopes", action="store_true",
                         help="include the names of nested scopes, not just module level ones")
    _project_option(listing)
    _environment_commands(commands)
    _configuration_commands(commands)
    return parser


def _position_command(commands: argparse._SubParsersAction, name: str, help: str,
                      live: bool = False) -> argparse.ArgumentParser:
    """A command reading one cursor position; ``live`` ones offer interpreter mode."""
    command = commands.add_parser(name, help=help,
                                  parents=[_SETTINGS] + ([_INTERPRETER] if live else []))
    command.add_argument("file", type=Path, help="Python source file to analyse")
    command.add_argument("line", type=int, help="1-based cursor line")
    command.add_argument("col", type=int, help="0-based cursor column")
    _project_option(command)
    return command


def _selection_command(commands: argparse._SubParsersAction, name: str,
                       help: str) -> argparse.ArgumentParser:
    """A command reading a region of the file, from the cursor to ``--until``."""
    command = _position_command(commands, name, help)
    command.add_argument("--until", type=_endpoint, required=True,
                         metavar="LINE:COL", help="1-based line and 0-based column to select to")
    command.add_argument("--name", required=True, help="the identifier to extract under")
    _diff_option(command)
    return command


def _environment_commands(commands: argparse._SubParsersAction) -> None:
    """``env``: what Python installations the machine offers."""
    actions = commands.add_parser("env", help="report the Python environments available")
    found = actions.add_subparsers(dest="action", required=True)
    found.add_parser("list", help="list every Python installation found",
                     parents=[_SETTINGS])
    search = found.add_parser("find-virtualenvs", help="list the virtualenvs found",
                              parents=[_SETTINGS])
    search.add_argument("--path", type=Path, help="a directory holding virtualenvs")
    details = found.add_parser("info", help="describe one Python environment",
                               parents=[_SETTINGS])
    details.add_argument("executable", nargs="?",
                         help="the interpreter to describe (default: the system one)")


def _configuration_commands(commands: argparse._SubParsersAction) -> None:
    """``project``: what a directory records about itself in ``.sith/project.json``."""
    actions = commands.add_parser("project", help="read and write the project configuration")
    start = actions.add_subparsers(dest="action", required=True).add_parser(
        "init", help="create or update .sith/project.json", parents=[_SETTINGS])
    start.add_argument("directory", nargs="?", type=Path, default=Path.cwd(),
                       help="the project root to configure (default: the working directory)")
    start.add_argument("--environment", help="the Python executable the project belongs to")
    start.add_argument("--sys-path", type=_paths,
                       help="comma separated import roots, replacing the detected ones")
    start.add_argument("--added-sys-path", type=_paths,
                       help="comma separated import roots to search as well")


def _diff_option(command: argparse.ArgumentParser) -> None:
    command.add_argument("--diff", action="store_true",
                         help="write a unified diff instead of the changed files")


def _endpoint(text: str) -> tuple[int, int]:
    """A ``line:col`` argument."""
    line, _, column = text.partition(":")
    if not line.isdigit() or not column.isdigit():
        raise argparse.ArgumentTypeError(f"expected LINE:COL, got {text!r}")
    return int(line), int(column)


def _paths(text: str) -> tuple[str, ...]:
    """A comma separated list of directories."""
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _project_option(command: argparse.ArgumentParser) -> None:
    command.add_argument("--project", type=Path, default=None,
                         help="project root (default: the directory holding the file)")


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        options.parse(arguments.settings)  # a bad setting fails before any work is done
        payload = _HANDLERS[arguments.command](arguments)
    except SithError as error:
        print(error, file=sys.stderr)
        return 1
    _write(payload)
    return 0


def _write(payload: Payload) -> None:
    """A diff goes out as the text it is; everything else as one JSON object."""
    if isinstance(payload, str):
        sys.stdout.write(payload)
        return
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def _where(arguments: argparse.Namespace) -> tuple[Path, int, int, Path | None]:
    return arguments.file, arguments.line, arguments.col, arguments.project


def _options(arguments: argparse.Namespace, root: Path) -> Options:
    """The settings, project configuration and namespaces of one request."""
    return Options.build(root, arguments.settings, _namespaces(arguments))


def _namespaces(arguments: argparse.Namespace) -> Namespaces | None:
    """The namespaces interpreter mode falls back to, which it may do without."""
    if arguments.namespaces is None:
        return None
    if not arguments.interpreter:
        raise SithError("--namespaces is only meaningful with --interpreter")
    return Namespaces.load(arguments.namespaces)


def _cursor_options(arguments: argparse.Namespace) -> Options:
    """The options of a command reading a file: its project root is the file's."""
    return _options(arguments, (arguments.project or arguments.file.parent).resolve())


def _complete(arguments: argparse.Namespace) -> Payload:
    found = engine.complete(*_where(arguments), fuzzy=arguments.fuzzy,
                            options=_cursor_options(arguments))
    return {"completions": [completion.as_dict() for completion in found]}


def _infer(arguments: argparse.Namespace) -> Payload:
    found = engine.infer(*_where(arguments), options=_cursor_options(arguments))
    return {"definitions": [definition.as_dict() for definition in found]}


def _goto(arguments: argparse.Namespace) -> Payload:
    found = engine.goto(*_where(arguments), follow=arguments.follow_imports,
                        options=_cursor_options(arguments))
    return {"definitions": [definition.as_dict() for definition in found]}


def _signatures(arguments: argparse.Namespace) -> Payload:
    found = engine.signatures(*_where(arguments), options=_cursor_options(arguments))
    return {"signatures": [signature.as_dict() for signature in found]}


def _context(arguments: argparse.Namespace) -> Payload:
    found = engine.context(*_where(arguments), options=_cursor_options(arguments))
    return {"context": [scope.as_dict() for scope in found]}


def _references(arguments: argparse.Namespace) -> Payload:
    found = engine.references(*_where(arguments), project_wide=arguments.scope == "project",
                              options=_cursor_options(arguments))
    return {"references": [occurrence.as_dict() for occurrence in found]}


def _rename(arguments: argparse.Namespace) -> Payload:
    found = engine.rename(*_where(arguments), new_name=arguments.new_name,
                          options=_cursor_options(arguments))
    return _reported(found, arguments)


def _inline(arguments: argparse.Namespace) -> Payload:
    return _reported(engine.inline(*_where(arguments), options=_cursor_options(arguments)),
                     arguments)


def _extract_variable(arguments: argparse.Namespace) -> Payload:
    found = engine.extract_variable(*_where(arguments), until=arguments.until,
                                    name=arguments.name, options=_cursor_options(arguments))
    return _reported(found, arguments)


def _extract_function(arguments: argparse.Namespace) -> Payload:
    found = engine.extract_function(*_where(arguments), until=arguments.until,
                                    name=arguments.name, options=_cursor_options(arguments))
    return _reported(found, arguments)


def _reported(refactoring: Refactoring, arguments: argparse.Namespace) -> Payload:
    return refactoring.diff() if arguments.diff else refactoring.as_dict()


def _errors(arguments: argparse.Namespace) -> Payload:
    return {"errors": [found.as_dict() for found in engine.errors(arguments.file)]}


def _search(arguments: argparse.Namespace) -> Payload:
    root = arguments.project.resolve()
    found = engine.search(arguments.query, root, options=_options(arguments, root))
    return {"results": [definition.as_dict(docstring=False) for definition in found]}


def _names(arguments: argparse.Namespace) -> Payload:
    found = engine.names(arguments.file, arguments.project, all_scopes=arguments.all_scopes,
                         options=_cursor_options(arguments))
    return {"names": [{**definition.as_dict(), "is_definition": True} for definition in found]}


def _environments(arguments: argparse.Namespace) -> Payload:
    return _ENVIRONMENTS[arguments.action](arguments)


def _env_list(arguments: argparse.Namespace) -> Payload:
    found = environments.installations(Path.cwd())
    return {"environments": [environment.as_dict() for environment in found]}


def _env_virtualenvs(arguments: argparse.Namespace) -> Payload:
    found = environments.virtualenvs(arguments.path, Path.cwd())
    return {"environments": [environment.as_dict() for environment in found]}


def _env_info(arguments: argparse.Namespace) -> Payload:
    """The environment asked for, or the one the project configures."""
    configured = ProjectConfig.load(Path.cwd()).environment_path
    return environments.info(arguments.executable, configured).as_dict(detailed=True)


def _project(arguments: argparse.Namespace) -> Payload:
    return _PROJECTS[arguments.action](arguments)


def _project_init(arguments: argparse.Namespace) -> Payload:
    """Write the configuration, keeping whatever the flags did not mention."""
    root = arguments.directory.resolve()
    config = ProjectConfig.load(root).merged(
        environment_path=arguments.environment,
        sys_path=arguments.sys_path,
        added_sys_path=arguments.added_sys_path,
        smart_sys_path=options.parse(arguments.settings).get("smart_sys_path"))
    return {**config.as_dict(), "path": str(config.write(root))}


_ENVIRONMENTS = {"list": _env_list, "find-virtualenvs": _env_virtualenvs, "info": _env_info}
_PROJECTS = {"init": _project_init}
_HANDLERS = {"complete": _complete, "infer": _infer, "goto": _goto,
             "signatures": _signatures, "context": _context, "references": _references,
             "search": _search, "names": _names, "rename": _rename, "inline": _inline,
             "extract-variable": _extract_variable, "extract-function": _extract_function,
             "errors": _errors, "env": _environments, "project": _project}


if __name__ == "__main__":
    sys.exit(main())
