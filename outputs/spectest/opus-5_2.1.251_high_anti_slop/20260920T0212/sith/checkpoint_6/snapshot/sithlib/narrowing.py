"""The ``if`` tests that constrain a name's type on a given line."""

import ast


def conditions(tree, line):
    """(test, taken) for every simple condition that holds on `line`.

    `taken` is False when the line sits in the ``else`` branch of the test, or
    under a ``not``. Outer statements come before the ones they nest, so later
    conditions refine earlier ones.
    """
    found = []
    for test, taken in _enclosing_tests(tree, line):
        found.extend(_flatten(test, taken))
    return found


def checked_class(test, name):
    """The second argument of ``isinstance(name, ...)``, or ``None``."""
    if not isinstance(test, ast.Call) or not _is_name(test.func, "isinstance"):
        return None
    if len(test.args) != 2 or not _is_name(test.args[0], name):
        return None
    return test.args[1]


def none_check(test, name):
    """``True`` for ``name is None``, ``False`` for ``name is not None``, else ``None``."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not _is_name(test.left, name) or not _is_none(test.comparators[0]):
        return None
    if isinstance(test.ops[0], ast.Is):
        return True
    return False if isinstance(test.ops[0], ast.IsNot) else None


def _enclosing_tests(tree, line):
    tests = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if _covers(node.body, line):
            tests.append((node.test, True))
        elif _covers(node.orelse, line):
            tests.append((node.test, False))
    return tests


def _covers(body, line):
    return bool(body) and body[0].lineno <= line <= body[-1].end_lineno


def _flatten(test, taken):
    """Split a test into the simple conditions it is made of."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _flatten(test.operand, not taken)
    if taken and isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return [part for value in test.values for part in _flatten(value, taken)]
    return [(test, taken)]


def _is_name(node, name):
    return isinstance(node, ast.Name) and node.id == name


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None
