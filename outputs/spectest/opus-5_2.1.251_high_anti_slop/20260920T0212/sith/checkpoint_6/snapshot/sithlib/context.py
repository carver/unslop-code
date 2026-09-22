"""The `context` command: the scopes the cursor sits inside."""

from .bindings import identifier_column
from .modules import project_at
from .scopes import innermost
from .source import locate


def context_scopes(path, line, column, options):
    """The class and function scopes holding the cursor, outermost one first.

    The module itself is left out, so a cursor at module level is in no scope
    at all.
    """
    module = project_at(options).module(path)
    cursor = locate(module.lines, line, column)
    scope = innermost(module.scope, cursor.line, cursor.indent)
    nesting = []
    while scope.parent is not None:
        nesting.append(_record(module, scope))
        scope = scope.parent
    return list(reversed(nesting))


def _record(module, scope):
    """Where the statement opening a scope is written, and what it opens."""
    node = scope.node
    return {
        "name": node.name,
        "type": scope.kind,
        "line": node.lineno,
        "column": identifier_column(module.lines, node.lineno, node.name, node.col_offset),
    }
