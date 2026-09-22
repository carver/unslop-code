"""Locating identifiers in a parsed module.

Most of this module is about the column an identifier really starts at:
``name_at`` finds the name a cursor is sitting on, ``name_column`` says where a
definition writes the name it introduces -- the ``f`` of ``def foo``, not the
``d``.  ``all_names`` hands out every identifier a module writes, which is what
searching for the uses of one needs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterator

_KEYWORDS = {ast.FunctionDef: "def ", ast.AsyncFunctionDef: "async def ", ast.ClassDef: "class "}


@dataclass(frozen=True)
class Reference:
    """The identifier under the cursor and the node that writes it."""

    name: str
    node: ast.AST


def name_at(tree: ast.Module, line: int, column: int) -> Reference | None:
    """The innermost name written at ``line``/``column``, or ``None``.

    The cursor counts as being on a name when it sits anywhere from its first
    character up to just past its last one.
    """
    candidates = [(end - start, reference)
                  for node in ast.walk(tree)
                  for lineno, start, end, reference in _names(node)
                  if lineno == line and start <= column <= end]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[0])[1]


def all_names(tree: ast.Module) -> Iterator[tuple[int, int, Reference]]:
    """Every identifier written in ``tree``, as ``(line, column, reference)``."""
    for node in ast.walk(tree):
        for lineno, start, _end, reference in _names(node):
            yield lineno, start, reference


def defines(node: ast.AST) -> bool:
    """Whether the identifier ``node`` writes is the one being defined there."""
    match node:
        case (ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef()
              | ast.alias() | ast.arg()):
            return True
        case ast.Name(ctx=context) | ast.Attribute(ctx=context):
            return isinstance(context, ast.Store)
        case _:
            return False


def name_column(node: ast.AST) -> int:
    """The column of the identifier ``node`` introduces."""
    keyword = _KEYWORDS.get(type(node))
    if keyword is not None:
        return node.col_offset + len(keyword)
    if isinstance(node, ast.alias) and node.asname:
        return node.end_col_offset - len(node.asname)
    return node.col_offset


def _names(node: ast.AST) -> Iterator[tuple[int, int, int, Reference]]:
    """The identifiers ``node`` writes, as ``(line, start, end, reference)``."""
    match node:
        case ast.Name(id=name) | ast.arg(arg=name):
            start = node.col_offset
            yield node.lineno, start, start + len(name), Reference(name, node)
        case ast.Attribute(attr=name):
            # The node ends at the end of the attribute, whatever lies between.
            yield (node.end_lineno, node.end_col_offset - len(name), node.end_col_offset,
                   Reference(name, node))
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            start = name_column(node)
            yield node.lineno, start, start + len(name), Reference(name, node)
        case ast.alias(name=name, asname=asname):
            bound = asname or name.split(".")[0]
            start = name_column(node)
            yield node.lineno, start, start + len(bound), Reference(bound, node)
