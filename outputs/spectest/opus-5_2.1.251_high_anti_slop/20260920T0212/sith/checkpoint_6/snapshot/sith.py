#!/usr/bin/env python3
"""Command-line code intelligence for Python sources.

    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--no-dynamic] [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--no-dynamic] [--project <dir>]
    python sith.py context <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]
    python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
    python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
    python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>
    python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>
    python sith.py errors <file>
    python sith.py env list
    python sith.py env find-virtualenvs [--path <dir>]
    python sith.py env info [<executable>]
    python sith.py project init [<dir>] [--environment <exe>] [--sys-path <paths>]
                                        [--added-sys-path <paths>]

Imports are resolved inside the project, whose root defaults to the directory
holding <file>, and type information comes from a `.pyi` stub when the project
ships one. A project configures itself through `.sith/project.json`, which
`project init` writes, and every command takes `--setting key=value` flags
overriding what that file asks for. The analysis commands also take
`--interpreter --namespaces <file>`, which lets the names a running
interpreter holds answer for whatever the source alone cannot.

Prints a JSON object to STDOUT holding a "completions", "definitions",
"signatures", "references", "context", "environments" or "errors" array, the
project file `project init` wrote, or the "changed_files" a refactoring
rewrites - as a unified diff with `--diff`.
"""

import json
import sys

from sithlib.cli import build_parser, project_updates
from sithlib.config import initialise
from sithlib.context import context_scopes
from sithlib.edits import rendered
from sithlib.engine import complete
from sithlib.environments import details, installed, virtualenvs
from sithlib.errors import SithError
from sithlib.extraction import extract_function, extract_variable
from sithlib.inlining import inline
from sithlib.navigation import goto, infer
from sithlib.options import options_for
from sithlib.references import references
from sithlib.renaming import rename
from sithlib.search import names, search
from sithlib.signatures import signatures
from sithlib.syntax import syntax_errors

_ENVIRONMENTS = {
    "list": lambda args, options: {"environments": installed(options.root)},
    "find-virtualenvs": lambda args, options: {
        "environments": virtualenvs(args.path, options.root),
    },
    "info": lambda args, options: {
        "environment": details(args.executable, options.project),
    },
}

_COMMANDS = {
    "complete": lambda args, options: {
        "completions": complete(args.file, args.line, args.col, args.fuzzy, options),
    },
    "infer": lambda args, options: {
        "definitions": infer(args.file, args.line, args.col, options, not args.no_dynamic),
    },
    "goto": lambda args, options: {
        "definitions": goto(args.file, args.line, args.col, args.follow_imports, options),
    },
    "signatures": lambda args, options: {
        "signatures": signatures(args.file, args.line, args.col, not args.no_dynamic, options),
    },
    "context": lambda args, options: {
        "context": context_scopes(args.file, args.line, args.col, options),
    },
    "references": lambda args, options: {
        "references": references(args.file, args.line, args.col, args.scope, options),
    },
    "search": lambda args, options: {"definitions": search(args.query, options)},
    "names": lambda args, options: {"definitions": names(args.file, args.all_scopes, options)},
    "errors": lambda args, options: {"errors": syntax_errors(args.file)},
    "env": lambda args, options: _ENVIRONMENTS[args.env_command](args, options),
    "project": lambda args, options: initialise(options.root, project_updates(args)),
    "rename": lambda args, options: rendered(
        rename(args.file, args.line, args.col, args.new_name, options), args.diff),
    "inline": lambda args, options: rendered(
        inline(args.file, args.line, args.col, options), args.diff),
    "extract-variable": lambda args, options: rendered(
        extract_variable(args.file, args.line, args.col, args.until, args.name, options),
        args.diff),
    "extract-function": lambda args, options: rendered(
        extract_function(args.file, args.line, args.col, args.until, args.name, options),
        args.diff),
}


def main(argv=None):
    arguments = build_parser(__doc__).parse_args(argv)
    try:
        payload = _COMMANDS[arguments.command](arguments, options_for(arguments))
    except SithError as error:
        print(f"sith: {error}", file=sys.stderr)
        return 1
    if isinstance(payload, str):
        sys.stdout.write(payload)
        return 0
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
