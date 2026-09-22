"""The scope context at a cursor: the definitions it is written inside."""

from __future__ import annotations

from typing import Dict, List

from .analysis import Analyzer, Scope, identifier_column
from .context import cursor_indent
from .definitions import document
from .source import Source


def context(source: Source, project, line: int, col: int) -> str:
    """What the cursor is written inside, outermost scope first."""
    analyzer = project.analyzer_for(source)
    indent = cursor_indent(source.line_at(line, col), col)
    enclosing = _enclosing(analyzer.scope_at(line, indent))
    return document(context=[_record(analyzer, scope) for scope in enclosing])


def _enclosing(scope: Scope) -> List[Scope]:
    """The named scopes holding a position, outermost first.

    The module scope is the one scope without a parent, and it is not part of
    the answer: a cursor at module level is inside nothing.
    """
    found = []
    while scope.parent is not None:
        found.append(scope)
        scope = scope.parent
    return list(reversed(found))


def _record(analyzer: Analyzer, scope: Scope) -> Dict:
    """One scope of the answer, placed at the name its definition declares."""
    node = scope.node
    return {
        "name": node.name,
        "type": scope.kind,
        "line": node.lineno,
        "column": identifier_column(analyzer.lines, node, node.name),
    }
