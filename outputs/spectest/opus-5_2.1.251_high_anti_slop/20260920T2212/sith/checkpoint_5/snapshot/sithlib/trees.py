"""The region of a file a refactoring was asked about, and the nodes it covers.

A refactoring is pointed at a span of text; what it may do with it depends on
what the span holds.  These functions turn a span into the expression written
exactly across it, the run of statements it covers, and the statement or
definition those sit inside.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterator

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class Span:
    """A region of one file: 1-based lines, 0-based columns, the end exclusive."""

    line: int
    column: int
    end_line: int
    end_column: int

    def matches(self, node: ast.AST) -> bool:
        """Whether ``node`` is written exactly across this span."""
        return ((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)
                == (self.line, self.column, self.end_line, self.end_column))

    def holds(self, line: int) -> bool:
        return self.line <= line <= self.end_line


def span_of(node: ast.AST) -> Span:
    """The region ``node`` is written across."""
    return Span(node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    """Every node's parent, for walking back up a tree that has no back links."""
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def expression_spanning(tree: ast.Module, span: Span) -> ast.expr | None:
    """The expression written exactly across ``span``, outermost first.

    A span that starts or ends inside an expression matches nothing, which is
    how a selection that cuts an expression in half is recognised.
    """
    return next((node for node in ast.walk(tree)
                 if isinstance(node, ast.expr) and span.matches(node)), None)


def statements_spanning(tree: ast.Module, span: Span) -> list[ast.stmt] | None:
    """The run of whole statements ``span`` covers, or ``None`` if it cuts one.

    The run has to fill the selected lines from one body of the tree: a span
    reaching from the middle of a statement, or stopping inside one, belongs to
    no body and is refused.
    """
    for body in _bodies(tree):
        run = [statement for statement in body
               if span.line <= statement.lineno and statement.end_lineno <= span.end_line]
        if run and _fills(span, run):
            return run
    return None


def statement_holding(tree: ast.Module, node: ast.AST) -> ast.stmt:
    """The statement ``node`` is written in."""
    ancestors = parents(tree)
    while not isinstance(node, ast.stmt):
        node = ancestors[node]
    return node


def definition_holding(tree: ast.Module, node: ast.AST) -> ast.stmt | None:
    """The innermost ``def`` or ``class`` around ``node``, or ``None`` at module level."""
    ancestors = parents(tree)
    while node in ancestors:
        node = ancestors[node]
        if isinstance(node, _DEFINITIONS):
            return node
    return None


def first_line(node: ast.stmt) -> int:
    """The line a definition starts at, counting the decorators above it."""
    decorators = getattr(node, "decorator_list", [])
    return min([node.lineno] + [decorator.lineno for decorator in decorators])


def _fills(span: Span, run: list[ast.stmt]) -> bool:
    """Whether ``run`` accounts for every line and column ``span`` selects."""
    return (run[0].lineno == span.line and run[-1].end_lineno == span.end_line
            and span.column <= run[0].col_offset
            and span.end_column >= run[-1].end_col_offset)


def _bodies(tree: ast.Module) -> Iterator[list[ast.stmt]]:
    """Every list of statements the tree holds, the outermost ones first."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            found = getattr(node, field, None)
            if isinstance(found, list) and found and isinstance(found[0], ast.stmt):
                yield found
