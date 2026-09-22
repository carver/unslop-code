"""Replacing a variable with the expression it was assigned.

Every reference to the name takes the text of the assignment's right hand side
and the assignment itself goes away.  The substituted text is bracketed where
the surrounding expression would otherwise regroup it: see
:mod:`sithlib.precedence`.
"""

from __future__ import annotations

import ast

from .cursor import Reference
from .definitions import Definition
from .edits import Edit, Refactoring, collect
from .errors import SithError
from .precedence import needs_parentheses
from .project import Analysis
from .references import matching, resolve
from .scopes import Scope
from .source import SourceFile
from .trees import parents, span_of


def inline(analysis: Analysis, source: SourceFile, reference: Reference, scope: Scope,
           line: int) -> Refactoring:
    """Write the value of the name at the cursor everywhere the name is read."""
    target = frozenset(resolve(reference, scope, line, follow=True))
    if any(definition.type in ("function", "class") for definition in target):
        raise SithError("cannot inline a function/class definition")
    assignment = _assignment(analysis.tree, reference.name, target)
    if assignment is None:
        raise SithError(f"cannot inline '{reference.name}': it is not a simple assignment")
    uses = [found for occurrence, found in matching(analysis, reference.name, target)
            if not occurrence.is_definition]
    if not uses:
        raise SithError("name has no references to inline")
    written = source.segment(span_of(assignment.value))
    ancestors = parents(analysis.tree)
    path = analysis.info.path
    edits = [_substitution(path, found.node, ancestors, assignment.value, written)
             for found in uses]
    edits.append(Edit(path, source.whole_lines(assignment.lineno, assignment.end_lineno), ""))
    return collect(edits, {path: source.text})


def _substitution(path: str, node: ast.AST, ancestors: dict[ast.AST, ast.AST],
                  value: ast.expr, written: str) -> Edit:
    """One reference replaced by the value, bracketed if its context demands it."""
    bracketed = needs_parentheses(value, ancestors[node], node)
    return Edit(path, span_of(node), f"({written})" if bracketed else written)


def _assignment(tree: ast.Module, name: str,
                target: frozenset[Definition]) -> ast.Assign | None:
    """The ``name = <expr>`` the cursor's definitions point at, if that is what they are."""
    sites = {(definition.line, definition.column) for definition in target}
    for node in ast.walk(tree):
        match node:
            case ast.Assign(targets=[ast.Name() as bound]) if bound.id == name and (
                    bound.lineno, bound.col_offset) in sites:
                return node
    return None
