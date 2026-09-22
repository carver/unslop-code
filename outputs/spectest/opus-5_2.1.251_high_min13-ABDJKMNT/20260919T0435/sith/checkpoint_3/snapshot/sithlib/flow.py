"""Flow-sensitive narrowing: what the `if` branches around the cursor promise.

Only the guards a conforming reader can be sure of are modelled: an
`isinstance` test pins a name to the classes it names, and a comparison against
`None` either pins the name to `None` or rules `None` out.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Narrowing:
    """What one branch says about one name inside its body."""

    #: Class expressions the name is known to be an instance of.
    types: tuple = ()
    #: True when the name is `None` here, False when it certainly is not.
    none: bool | None = None


def narrowings(module: ast.Module, name: str, line: int) -> list[Narrowing]:
    """Constraints on `name` from the branches containing `line`, outermost first."""
    found = []
    for node in ast.walk(module):
        if not isinstance(node, ast.If):
            continue
        for suite, taken in ((node.body, True), (node.orelse, False)):
            constraint = _constraint(node.test, name, taken) if _covers(suite, line) else None
            if constraint is not None:
                found.append((node.lineno, constraint))
    return [constraint for _, constraint in sorted(found, key=lambda pair: pair[0])]


def _covers(suite: list[ast.stmt], line: int) -> bool:
    """Whether a branch body spans `line`."""
    if not suite:
        return False
    last = suite[-1]
    return suite[0].lineno <= line <= (last.end_lineno or last.lineno)


def _constraint(test: ast.expr, name: str, taken: bool) -> Narrowing | None:
    """What taking (or not taking) `test` says about `name`."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and taken:
        return _merge(_constraint(value, name, True) for value in test.values)
    if isinstance(test, ast.Call):
        classes = _isinstance_classes(test, name)
        return Narrowing(types=classes) if classes and taken else None
    if isinstance(test, ast.Compare):
        is_none = _none_comparison(test, name)
        return None if is_none is None else Narrowing(none=is_none == taken)
    return None


def _merge(constraints) -> Narrowing | None:
    """Fold the constraints of an `and` chain into one."""
    kept = [constraint for constraint in constraints if constraint is not None]
    if not kept:
        return None
    nones = [constraint.none for constraint in kept if constraint.none is not None]
    types = tuple(node for constraint in kept for node in constraint.types)
    return Narrowing(types=types, none=nones[0] if nones else None)


def _isinstance_classes(test: ast.Call, name: str) -> tuple:
    """The classes of an `isinstance(name, ...)` call, if that is what `test` is."""
    matches = isinstance(test.func, ast.Name) and test.func.id == "isinstance"
    if not (matches and len(test.args) == 2 and _is_name(test.args[0], name)):
        return ()
    classes = test.args[1]
    if isinstance(classes, (ast.Tuple, ast.List)):
        return tuple(classes.elts)
    return (classes,)


def _none_comparison(test: ast.Compare, name: str) -> bool | None:
    """True for `name is None`, False for `name is not None`, None for anything else."""
    if len(test.ops) != 1 or not _is_name(test.left, name):
        return None
    if not _is_none(test.comparators[0]):
        return None
    return {ast.Is: True, ast.IsNot: False}.get(type(test.ops[0]))


def _is_name(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None
