"""The `inline` subcommand.

Inlining writes a variable's value where its name was and drops the
assignment. The value is copied as it was written, wrapped in parentheses
wherever the expression it lands in would otherwise regroup it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

from .analysis import merged
from .edits import Edit, RefactorError, Refactoring, line_span, rewrite, source_text
from .navigation import BINDINGS, Query, name_at
from .precedence import needs_parentheses
from .project import Project
from .references import Reference, project_occurrences, spelled
from .source import Source
from .symbols import Symbol

ASSIGNMENTS = (ast.Assign, ast.AnnAssign)
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

Occurrence = Tuple[Path, Reference]
"""One place a name is written, and the file it is written in."""


def inline(source: Source, project: Project, line: int, col: int, diff: bool) -> str:
    """Replace every reference to the name at the cursor with its value."""
    query = Query.at(source, project, line, col)
    name = spelled(query.node)
    symbol = _inlined_symbol(query, name)
    found = project_occurrences(query, project, name)
    uses = [place for place in found if not place[1].is_definition]
    _check_inlinable(name, found, uses)
    value = symbol.node.value
    text = source_text(symbol.origin.lines, value)
    edits = [_use_edit(project, place, name, value, text) for place in uses]
    edits.append(line_span(symbol.origin.path, symbol.node.lineno, symbol.node.end_lineno, ""))
    return Refactoring(project.root, edits).report(diff)


def _inlined_symbol(query: Query, name: str) -> Symbol:
    """The binding the cursor's name has, if it is one that can be inlined."""
    symbol = merged(BINDINGS[type(query.node)](query))
    node = symbol.node if symbol is not None else None
    if isinstance(node, DEFINITIONS):
        raise RefactorError("cannot inline a function/class definition")
    if not isinstance(node, ASSIGNMENTS) or node.value is None:
        raise RefactorError(f"{name} is not a simple assignment")
    return symbol


def _check_inlinable(name: str, found: List[Occurrence], uses: List[Occurrence]) -> None:
    """Refuse a name that is written more than once or read nowhere."""
    if len(found) - len(uses) != 1:
        raise RefactorError(f"{name} is defined more than once, so it cannot be inlined")
    if not uses:
        raise RefactorError("name has no references to inline")


def _use_edit(project: Project, place: Occurrence, name: str, value: ast.expr, text: str) -> Edit:
    """Write the assigned value at one place the name is read."""
    path, found = place
    analyzer = project.analyzer_at(path)
    node, parents = name_at(analyzer.tree, analyzer.lines, found.line, found.column)
    written = f"({text})" if needs_parentheses(value, text, parents[-1], node) else text
    return rewrite(path, found.line, found.column, name, written)
