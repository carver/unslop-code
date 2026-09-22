"""How tightly expressions bind, and where an inlined one needs parentheses."""

import ast

_TUPLE = 0          # a bare comma-separated tuple, which binds loosest of all
_BRACKETED = 1      # what a slot already surrounded by brackets accepts
_COMPARISON = 6
_ATOM = 18          # a name, a call, a literal: nothing can pull it apart

_OPERATORS = {
    ast.Or: 3, ast.And: 4,
    ast.BitOr: 7, ast.BitXor: 8, ast.BitAnd: 9,
    ast.LShift: 10, ast.RShift: 10,
    ast.Add: 11, ast.Sub: 11,
    ast.Mult: 12, ast.MatMult: 12, ast.Div: 12, ast.FloorDiv: 12, ast.Mod: 12,
    ast.Not: 5, ast.UAdd: 13, ast.USub: 13, ast.Invert: 13,
    ast.Pow: 14,
}

_FIXED = {
    ast.Tuple: _TUPLE, ast.Starred: _TUPLE,
    ast.Lambda: _BRACKETED, ast.IfExp: _BRACKETED, ast.NamedExpr: _BRACKETED,
    ast.Yield: _BRACKETED, ast.YieldFrom: _BRACKETED,
    ast.Compare: _COMPARISON,
    ast.Await: 15,
}

# Slots holding a whole expression, where even a bare tuple keeps its meaning.
_WHOLE_VALUE = {
    (ast.Expr, "value"), (ast.Assign, "value"), (ast.AnnAssign, "value"),
    (ast.AugAssign, "value"), (ast.Return, "value"), (ast.Yield, "value"),
    (ast.For, "iter"), (ast.AsyncFor, "iter"),
}


def precedence(node):
    """How tightly an expression binds; a higher level binds tighter."""
    if isinstance(node, (ast.BoolOp, ast.BinOp, ast.UnaryOp)):
        return _OPERATORS[type(node.op)]
    return _FIXED.get(type(node), _ATOM)


def slots(tree):
    """id(node) -> (parent, field name) for every node under `tree`."""
    found = {}
    for parent in ast.walk(tree):
        for name, value in ast.iter_fields(parent):
            for child in (value if isinstance(value, list) else [value]):
                if isinstance(child, ast.AST):
                    found[id(child)] = (parent, name)
    return found


def parenthesized(text, value, slot):
    """`text` wrapped in parentheses when its slot would otherwise re-associate it.

    A tuple written with parentheses carries them inside its own source span,
    so its text already binds as tightly as an atom does.
    """
    written = isinstance(value, ast.Tuple) and text.startswith("(")
    bound = _ATOM if written else precedence(value)
    return text if bound >= _required(*slot) else f"({text})"


def _required(parent, name):
    """The tightest binding the slot `name` of `parent` accepts without parentheses."""
    handler = _SLOTS.get(type(parent))
    if handler is not None:
        return handler(parent, name)
    return _TUPLE if (type(parent), name) in _WHOLE_VALUE else _BRACKETED


def _operand(parent, name):
    """The level a binary operand needs, the tighter side being the one that re-groups."""
    tighter = name == ("left" if isinstance(parent.op, ast.Pow) else "right")
    return precedence(parent) + (1 if tighter else 0)


def _receiver(_parent, name):
    """A dotted, called or indexed expression must be an atom; its arguments need not."""
    return _ATOM if name in ("value", "func") else _BRACKETED


_SLOTS = {
    ast.BoolOp: lambda parent, name: precedence(parent),
    ast.BinOp: _operand,
    ast.UnaryOp: lambda parent, name: precedence(parent),
    ast.Compare: lambda parent, name: _COMPARISON + 1,
    ast.Attribute: _receiver,
    ast.Subscript: _receiver,
    ast.Call: _receiver,
    ast.Await: lambda parent, name: _ATOM,
    ast.IfExp: lambda parent, name: _BRACKETED + 1,
}
