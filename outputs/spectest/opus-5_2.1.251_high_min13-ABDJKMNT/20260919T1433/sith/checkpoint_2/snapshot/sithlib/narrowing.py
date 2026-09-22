"""Flow-sensitive narrowing: what the branch a cursor sits in says about a name.

An `if` test constrains the names it mentions for the length of the branch it
guards, so a lookup made inside that branch answers with the narrowed value
rather than with everything the name could hold elsewhere.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from .analysis import Analyzer, instance_of, merged, soft_end
from .runtime import NONE, Value, union, without_none
from .symbols import Symbol


@dataclass
class Guard:
    """What a taken branch says about one name."""

    name: str
    narrow: Callable[[Optional[Value]], Optional[Value]]


def narrowed_lookup(
    analyzer: Analyzer, visible: Dict[str, List[Symbol]], line: int, indent: int
) -> Callable[[str], Optional[Symbol]]:
    """A name lookup at the cursor, with the branch narrowing applied."""

    def plain(name: str) -> Optional[Symbol]:
        return merged(visible.get(name, []))

    def resolve(expression: ast.expr) -> Optional[Value]:
        return analyzer.resolve(expression, plain)

    guards = [
        guard
        for test, taken in branches_at(analyzer, line, indent)
        for guard in guards_of(resolve, test, taken)
    ]

    def lookup(name: str) -> Optional[Symbol]:
        symbol = plain(name)
        for guard in guards:
            if symbol is not None and guard.name == name:
                symbol = replace(symbol, value=guard.narrow(symbol.value))
        return symbol

    return lookup


def branches_at(analyzer: Analyzer, line: int, indent: int) -> Iterator[Tuple[ast.expr, bool]]:
    """Every `if` test the cursor is under, with the arm it sits in.

    Outer branches come first, so a nested test narrows on top of the one
    enclosing it.
    """
    for node in ast.walk(analyzer.tree):
        if not isinstance(node, ast.If):
            continue
        if _holds(node, node.body, line, indent, analyzer.lines):
            yield node.test, True
        elif _holds(node, node.orelse, line, indent, analyzer.lines):
            yield node.test, False


def _holds(node: ast.If, block: List[ast.stmt], line: int, indent: int, lines: List[str]) -> bool:
    """Whether a cursor sits in a branch body, including a line being typed."""
    if not block:
        return False
    if block[0].lineno <= line <= block[-1].end_lineno:
        return True
    return line <= soft_end(block[-1], lines) and indent > node.col_offset


def guards_of(resolve, test: ast.expr, taken: bool) -> Iterator[Guard]:
    """The guards implied by ``test`` having the outcome ``taken``."""
    reader = GUARD_READERS.get(type(test))
    return reader(resolve, test, taken) if reader is not None else iter(())


def _negated_guards(resolve, test: ast.UnaryOp, taken: bool) -> Iterator[Guard]:
    """`not x` guards whatever `x` guards, the other way round."""
    if isinstance(test.op, ast.Not):
        yield from guards_of(resolve, test.operand, not taken)


def _conjunction_guards(resolve, test: ast.BoolOp, taken: bool) -> Iterator[Guard]:
    """Every operand of an `and` holds when the branch is taken."""
    if isinstance(test.op, ast.And) and taken:
        for operand in test.values:
            yield from guards_of(resolve, operand, True)


def _isinstance_guards(resolve, test: ast.Call, taken: bool) -> Iterator[Guard]:
    """`isinstance(x, C)` makes `x` a `C` for the body of the branch."""
    if not taken or not _is_isinstance(test) or not isinstance(test.args[0], ast.Name):
        return
    classes = test.args[1]
    written = classes.elts if isinstance(classes, ast.Tuple) else [classes]
    narrowed = union([instance_of(resolve(entry)) for entry in written])
    if narrowed is not None:
        yield Guard(test.args[0].id, lambda current: narrowed)


def _is_isinstance(test: ast.Call) -> bool:
    return isinstance(test.func, ast.Name) and test.func.id == "isinstance" and len(test.args) == 2


def _none_guards(resolve, test: ast.Compare, taken: bool) -> Iterator[Guard]:
    """`x is None` and `x is not None` decide whether `None` survives."""
    if not isinstance(test.left, ast.Name) or len(test.ops) != 1:
        return
    negated = isinstance(test.ops[0], ast.IsNot)
    if not isinstance(test.ops[0], (ast.Is, ast.IsNot)) or not _is_none_literal(test.comparators[0]):
        return
    if taken != negated:
        yield Guard(test.left.id, lambda current: NONE)
    else:
        yield Guard(test.left.id, without_none)


def _is_none_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


GUARD_READERS = {
    ast.UnaryOp: _negated_guards,
    ast.BoolOp: _conjunction_guards,
    ast.Call: _isinstance_guards,
    ast.Compare: _none_guards,
}
