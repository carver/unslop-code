"""Locating the AST nodes that a cursor, or a selected region, covers."""

from __future__ import annotations

import ast

from .source import SithError

Position = tuple[int, int]

#: The statements a new function or a new name is written next to.
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def parse(text: str, path: str) -> ast.Module:
    """Parse a file a refactoring is about to rewrite.

    Unlike browsing commands, a refactoring may not guess at broken source:
    an edit computed from a repaired tree would be written to positions that
    are not there.
    """
    try:
        return ast.parse(text)
    except SyntaxError as error:
        raise SithError(f"cannot parse {path}: {error.msg} at line {error.lineno}") from error


def parents(tree: ast.AST) -> dict[int, tuple[ast.AST, str]]:
    """Each node's parent and the field holding it, keyed by the child's identity."""
    found = {}
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    found[id(child)] = (node, field)
    return found


def span(node: ast.AST) -> tuple[Position, Position]:
    """Where a node starts and stops, as 1-based lines and 0-based columns."""
    return (node.lineno, node.col_offset), (node.end_lineno, node.end_col_offset)


def expression_spanning(tree: ast.AST, start: Position, end: Position) -> ast.expr | None:
    """The outermost expression written exactly from `start` up to `end`."""
    for node in ast.walk(tree):  # breadth first, so the outermost match comes first
        if isinstance(node, ast.expr) and span(node) == (start, end):
            return node
    return None


def statements_between(tree: ast.AST, first: int, last: int) -> list[ast.stmt]:
    """The sibling statements filling lines `first` to `last`, or none of them.

    A run that leaves part of a statement outside the lines is no run at all,
    which is how a selection cutting a statement in half is recognised.
    """
    for body in _bodies(tree):
        inside = [node for node in body if first <= node.lineno and node.end_lineno <= last]
        if inside and inside[0].lineno == first and inside[-1].end_lineno == last:
            return inside
    return []


def statement_containing(tree: ast.AST, position: Position) -> ast.stmt | None:
    """The innermost statement whose source holds a position, if one does."""
    holders = [
        statement
        for statement in ast.walk(tree)
        if isinstance(statement, ast.stmt) and _holds(statement, position)
    ]
    return max(holders, key=lambda statement: span(statement)[0], default=None)


def enclosing_definition(tree: ast.AST, line: int) -> ast.stmt | None:
    """The innermost function or class whose body holds `line`, if any.

    A definition written *on* the line does not hold it: code selected from
    its header down belongs to whatever the definition itself sits in.
    """
    holders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, DEFINITIONS) and node.lineno < line <= node.end_lineno
    ]
    return max(holders, key=lambda node: node.lineno, default=None)


def header_line(node: ast.stmt) -> int:
    """The first line a definition is written on, decorators included."""
    return min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])])


def name_at(tree: ast.AST, position: Position) -> ast.Name | None:
    """The name written at a position, as a reference reports it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and (node.lineno, node.col_offset) == position:
            return node
    return None


def _bodies(tree: ast.AST):
    """Every list of statements in the tree, outermost blocks first."""
    for node in ast.walk(tree):
        for _, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                yield value


def _holds(statement: ast.stmt, position: Position) -> bool:
    start, end = span(statement)
    return start <= position <= end
