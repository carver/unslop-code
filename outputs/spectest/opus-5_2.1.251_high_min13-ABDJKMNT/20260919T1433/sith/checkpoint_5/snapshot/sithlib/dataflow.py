"""What a run of statements reads and what it writes.

Moving statements into a function of their own needs both lists: the names the
block reads without having set them, which become its parameters, and the
names it sets, which are candidates for what it returns.
"""

from __future__ import annotations

import ast
from typing import Iterator, List, Sequence

DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class Flow:
    """The names a block of statements reads before setting, and the ones it sets.

    Both lists keep the order the names first appear in, which is the order
    the extracted function declares its parameters in.
    """

    def __init__(self, statements: Sequence[ast.stmt]):
        self.reads: List[str] = []
        self.writes: List[str] = []
        for statement in statements:
            self._visit(statement)

    def _visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            self._name(node.target.id, read=True)  # `x += 1` reads x before setting it
        for child in _in_order(node):
            self._visit(child)
        self._record(node)

    def _record(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._name(node.id, read=isinstance(node.ctx, ast.Load))
        elif isinstance(node, ast.arg):
            self._name(node.arg, read=False)
        elif isinstance(node, DEFINITION_NODES):
            self._name(node.name, read=False)
        elif isinstance(node, ast.alias):
            self._name(node.asname or node.name.split(".")[0], read=False)

    def _name(self, name: str, read: bool) -> None:
        """Record one use of a name; a read only counts before the block sets it."""
        if not read:
            if name not in self.writes:
                self.writes.append(name)
        elif name not in self.writes and name not in self.reads:
            self.reads.append(name)


def names_read_after(scope: ast.AST, line: int) -> List[str]:
    """Names read below a line in the scope the selection was taken from."""
    return [
        node.id for node in ast.walk(scope)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.lineno > line
    ]


def _in_order(node: ast.AST) -> Iterator[ast.AST]:
    """A node's children in the order they are evaluated.

    The tree keeps an assignment's targets before its value, but the value is
    what runs first, and reading a name the same statement then rebinds still
    counts as a read.
    """
    order = ORDERS.get(type(node))
    return iter(order(node)) if order is not None else ast.iter_child_nodes(node)


def _loop_order(node) -> List[ast.AST]:
    return [node.iter, node.target, *node.body, *node.orelse]


def _annotated_order(node) -> List[ast.AST]:
    return [child for child in (node.value, node.annotation, node.target) if child is not None]


ORDERS = {
    ast.Assign: lambda node: [node.value, *node.targets],
    ast.AnnAssign: _annotated_order,
    ast.AugAssign: lambda node: [node.value, node.target],
    ast.For: _loop_order,
    ast.AsyncFor: _loop_order,
    ast.comprehension: lambda node: [node.iter, node.target, *node.ifs],
}
