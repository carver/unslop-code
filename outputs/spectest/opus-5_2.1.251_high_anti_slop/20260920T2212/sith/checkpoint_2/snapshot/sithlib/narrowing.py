"""Type narrowing from the test guarding a branch.

``isinstance`` and ``is None`` tests say more about a name inside the branch
they guard than its binding does, so an ``if`` records what it proves about the
lines it owns and the lines its ``else`` owns.
"""

from __future__ import annotations

import ast
from typing import Callable, Iterator

from .inference import infer, instantiate
from .scopes import Narrowing, Scope
from .values import NONE, Union, Value, union


def narrowings(test: ast.expr, scope: Scope, start: int, end: int,
               positive: bool) -> list[Narrowing]:
    """What ``test`` proves about lines ``start``..``end`` of ``scope``.

    ``positive`` distinguishes the body of an ``if`` from its ``else``.
    """
    return [Narrowing(name, start, end, refine)
            for name, refine in _refinements(test, scope, positive)]


def _refinements(test: ast.expr, scope: Scope,
                 positive: bool) -> Iterator[tuple[str, Callable[[Value], Value]]]:
    """The ``(name, refine)`` pairs a test implies when it holds."""
    match test:
        case ast.BoolOp(op=ast.And(), values=values) if positive:
            for value in values:
                yield from _refinements(value, scope, positive)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            yield from _refinements(operand, scope, not positive)
        case ast.Call(func=ast.Name(id="isinstance"),
                      args=[ast.Name(id=name), classes]) if positive:
            yield name, lambda _: _instances(classes, scope)
        case ast.Compare(left=ast.Name(id=name), ops=[ast.Is() | ast.IsNot() as operator],
                         comparators=[ast.Constant(value=None)]):
            if isinstance(operator, ast.Is) is positive:
                yield name, lambda _: NONE
            else:
                yield name, _without_none


def _instances(classes: ast.expr, scope: Scope) -> Value:
    """The instances the second argument of ``isinstance`` allows."""
    elements = classes.elts if isinstance(classes, ast.Tuple) else [classes]
    return union([instantiate(infer(element, scope, classes.lineno)) for element in elements])


def _without_none(value: Value) -> Value:
    """``value`` with ``None`` dropped, for the branch where it cannot be None."""
    members = value.values if isinstance(value, Union) else (value,)
    return union([member for member in members if member != NONE])
