"""What a refactoring was asked to work on: a name, an expression, statements."""

import ast
from dataclasses import dataclass

from .errors import SithError


@dataclass(frozen=True)
class Span:
    """The region a selection covers, in 1-based lines and 0-based columns."""

    line: int
    column: int
    until_line: int
    until_column: int


def span_of(line, column, until):
    """The span a cursor and an ``--until <line>:<col>`` option describe."""
    head, _, tail = until.partition(":")
    if not (head.isdigit() and tail.isdigit()):
        raise SithError(f"--until must be <line>:<col>, not {until!r}")
    return Span(line, column, int(head), int(tail))


def check_identifier(name):
    """Refuse a name Python would not accept as an identifier."""
    if not name.isidentifier():
        raise SithError(f"not a valid Python identifier: {name!r}")


def expression_at(tree, span):
    """The outermost expression the span covers exactly."""
    found = [node for node in ast.walk(tree)
             if isinstance(node, ast.expr) and _spans(node, span)]
    if not found:
        raise SithError("selection is not a complete expression")
    return max(found, key=lambda node: len(list(ast.walk(node))))


def statements_at(tree, lines, span):
    """The run of whole statements the span covers, in the body holding them."""
    for body in _bodies(tree):
        first = _index(body, lambda node: _starts_at(lines, node, span))
        last = _index(body, lambda node: _ends_at(lines, node, span))
        if first is not None and last is not None and first <= last:
            return body[first:last + 1]
    raise SithError("selection is not a complete run of statements")


def enclosing_statement(tree, node):
    """The statement the expression `node` is part of."""
    found = [statement for statement in ast.walk(tree)
             if isinstance(statement, ast.stmt) and _holds(statement, node)]
    return min(found, key=lambda statement: len(list(ast.walk(statement))))


def _bodies(tree):
    """Every list of statements the tree holds, outermost first."""
    for node in ast.walk(tree):
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _index(body, matches):
    """Where the first statement a test accepts sits in a body, if one does."""
    return next((index for index, node in enumerate(body) if matches(node)), None)


def _spans(node, span):
    return ((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)
            == (span.line, span.column, span.until_line, span.until_column))


def _holds(statement, node):
    """Whether a statement covers the position an expression starts at."""
    start = (statement.lineno, statement.col_offset)
    return start <= (node.lineno, node.col_offset) <= (statement.end_lineno,
                                                       statement.end_col_offset)


def _starts_at(lines, node, span):
    """Whether a statement opens the selection, ignoring the indent before it."""
    return (node.lineno == span.line and span.column <= node.col_offset
            and not lines[node.lineno - 1][span.column:node.col_offset].strip())


def _ends_at(lines, node, span):
    """Whether a statement closes the selection, ignoring the blank tail after it."""
    return (node.end_lineno == span.until_line and span.until_column >= node.end_col_offset
            and not lines[node.end_lineno - 1][node.end_col_offset:span.until_column].strip())
