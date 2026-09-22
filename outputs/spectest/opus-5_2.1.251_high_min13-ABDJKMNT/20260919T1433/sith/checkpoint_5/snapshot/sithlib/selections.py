"""Reading the code a selection covers.

A selection is a pair of positions. `extract-variable` needs the expression it
covers exactly; `extract-function` needs the run of whole statements it covers.
Neither accepts a range that cuts a piece of syntax in half.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from .edits import RefactorError

DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
BODY_FIELDS = ("body", "orelse", "finalbody")
OPENING, CLOSING = "( \t", ") \t"
"""What a selection may hold before and after an expression and still be it."""


@dataclass(frozen=True)
class Selection:
    """The range of a file a command was asked to work on."""

    line: int
    column: int
    until_line: int
    until_column: int

    @classmethod
    def between(cls, line: int, column: int, until: Tuple[int, int], lines: Sequence[str]):
        """A selection from a cursor to an ``--until`` position.

        A range that stops at the start of a line is how an editor writes
        whole lines, so it is read as ending where the line before it ends.
        """
        until_line, until_column = until
        if until_column == 0 and until_line > line:
            until_line -= 1
            until_column = len(lines[until_line - 1])
        if (until_line, until_column) < (line, column):
            raise RefactorError("selection ends before it starts")
        return cls(line, column, until_line, until_column)

    def covers(self, line: int) -> bool:
        """Whether a line lies inside the selection."""
        return self.line <= line <= self.until_line


def selected_expression(tree: ast.Module, selection: Selection, lines: Sequence[str]) -> ast.expr:
    """The expression a selection covers, brackets around it allowed."""
    inside = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.expr) and _inside(node, selection)
    ]
    covered = [node for node in inside if _padded_only(node, selection, lines)]
    if not covered:
        raise RefactorError("selection is not a complete expression")
    return covered[0]


def selected_statements(tree: ast.Module, selection: Selection) -> List[ast.stmt]:
    """The run of whole statements a selection covers."""
    for body in _bodies(tree):
        run = _complete_run(body, selection)
        if run:
            return run
    raise RefactorError("selection is not one or more complete statements")


def statement_around(tree: ast.Module, node: ast.expr) -> ast.stmt:
    """The innermost statement whose span covers a node."""
    covering = [
        statement for statement in ast.walk(tree)
        if isinstance(statement, ast.stmt) and _covers(statement, node)
    ]
    return max(covering, key=lambda statement: (statement.lineno, statement.col_offset))


def enclosing_definition(tree: ast.Module, selection: Selection) -> Optional[ast.stmt]:
    """The innermost function or class holding a selection, if any does."""
    holding = [
        node for node in ast.walk(tree)
        if isinstance(node, DEFINITION_NODES)
        and node.lineno <= selection.line and node.end_lineno >= selection.until_line
    ]
    return max(holding, key=lambda node: node.lineno, default=None)


def first_line(node: ast.stmt) -> int:
    """The line a definition starts on, counting the decorators above it."""
    return min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])


def _complete_run(body: List[ast.stmt], selection: Selection) -> Optional[List[ast.stmt]]:
    """The statements of one body a selection covers, if it covers them whole."""
    touching = [
        statement for statement in body
        if statement.lineno <= selection.until_line and statement.end_lineno >= selection.line
    ]
    if not touching:
        return None
    first, last = touching[0], touching[-1]
    cuts_a_line = first.lineno < selection.line or last.end_lineno > selection.until_line
    cuts_a_statement = (
        selection.column > first.col_offset or selection.until_column < last.end_col_offset
    )
    return None if cuts_a_line or cuts_a_statement else touching


def _bodies(tree: ast.Module) -> Iterator[List[ast.stmt]]:
    """Every list of statements in a file, the module's own included."""
    for node in ast.walk(tree):
        for field in BODY_FIELDS:
            body = getattr(node, field, None)
            if body and isinstance(body[0], ast.stmt):
                yield body


def _inside(node: ast.expr, selection: Selection) -> bool:
    """Whether a node lies within the selected range."""
    return (
        (node.lineno, node.col_offset) >= (selection.line, selection.column)
        and (node.end_lineno, node.end_col_offset) <= (selection.until_line, selection.until_column)
    )


def _padded_only(node: ast.expr, selection: Selection, lines: Sequence[str]) -> bool:
    """Whether a selection holds a node plus balanced brackets and spaces.

    Selecting `(value)` selects the expression `value`; selecting `(value`
    cuts a bracket in half and is no expression at all.
    """
    before = _between(lines, (selection.line, selection.column), (node.lineno, node.col_offset))
    after = _between(
        lines, (node.end_lineno, node.end_col_offset), (selection.until_line, selection.until_column)
    )
    balanced = before.count("(") == after.count(")")
    return balanced and _only(before, OPENING) and _only(after, CLOSING)


def _only(text: str, allowed: str) -> bool:
    """Whether a text is made of allowed characters alone."""
    return all(character in allowed for character in text)


def _between(lines: Sequence[str], start: Tuple[int, int], end: Tuple[int, int]) -> str:
    """The text between two positions of a file."""
    if start[0] == end[0]:
        return lines[start[0] - 1][start[1]:end[1]]
    head = lines[start[0] - 1][start[1]:]
    return "".join([head, *lines[start[0]:end[0] - 1], lines[end[0] - 1][:end[1]]])


def _covers(statement: ast.stmt, node: ast.expr) -> bool:
    """Whether a statement's span holds a node's span."""
    return (
        (statement.lineno, statement.col_offset) <= (node.lineno, node.col_offset)
        and (statement.end_lineno, statement.end_col_offset)
        >= (node.end_lineno, node.end_col_offset)
    )
