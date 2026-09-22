"""The `context` command: the scopes the cursor is written inside."""

from __future__ import annotations

from .analysis import Analysis
from .options import DEFAULT, Options
from .scopes import Scope


def context(path: str, line: int, col: int, project: str | None = None,
            options: Options = DEFAULT) -> list[dict]:
    """The class and function scopes holding the cursor, outermost first.

    The module scope itself is not reported: a cursor written at module level
    is inside nothing.
    """
    analysis = Analysis.at(path, line, col, project, options=options)
    return [_record(scope) for scope in reversed(list(_enclosing(analysis.scope)))]


def _enclosing(scope: Scope):
    """The scope the cursor is in and those around it, innermost first."""
    while scope is not None and scope.kind != "module":
        yield scope
        scope = scope.parent


def _record(scope: Scope) -> dict:
    """One scope, located at the `def` or `class` statement that opens it."""
    return {
        "name": scope.node.name,
        "type": scope.kind,
        "line": scope.node.lineno,
        "column": scope.node.col_offset,
    }
