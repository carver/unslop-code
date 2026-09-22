"""Where a substituted expression needs brackets to keep its meaning.

Putting an expression where a name stood can change how the result is grouped:
``a + b`` written where ``x`` stands in ``x * 2`` has to become ``(a + b) * 2``.
Operators are ranked here the way Python's grammar ranks them, and a
substitution is bracketed when it binds more loosely than the slot it lands in.
"""

from __future__ import annotations

import ast

_BINARY = {ast.BitOr: 7, ast.BitXor: 8, ast.BitAnd: 9, ast.LShift: 10, ast.RShift: 10,
           ast.Add: 11, ast.Sub: 11, ast.Mult: 12, ast.MatMult: 12, ast.Div: 12,
           ast.FloorDiv: 12, ast.Mod: 12, ast.Pow: 14}

_ATOM = 17


def needs_parentheses(value: ast.expr, parent: ast.AST, slot: ast.AST) -> bool:
    """Whether ``value`` must be bracketed to stand where ``slot`` does in ``parent``."""
    return _binds(value) < _required(parent, slot)


def _binds(node: ast.expr) -> int:
    """How tightly ``node`` holds together; an atom holds tightest."""
    match node:
        case ast.Tuple() | ast.Starred() | ast.Slice() | ast.Yield() | ast.YieldFrom():
            return 0  # a comma, a colon or a yield is looser than any operator
        case ast.NamedExpr():
            return 1
        case ast.Lambda() | ast.IfExp():
            return 2
        case ast.BoolOp(op=ast.Or()):
            return 3
        case ast.BoolOp():
            return 4
        case ast.UnaryOp(op=ast.Not()):
            return 5
        case ast.Compare():
            return 6
        case ast.BinOp(op=op):
            return _BINARY[type(op)]
        case ast.UnaryOp():
            return 13
        case ast.Await():
            return 15
        case _:
            return _ATOM


def _required(parent: ast.AST, slot: ast.AST) -> int:
    """How tightly a child must bind to sit unbracketed where ``slot`` sits."""
    match parent:
        case ast.stmt():
            return 0  # a statement takes any expression, commas included
        case ast.BinOp(left=left, op=op):
            # Every binary operator associates to the left, except ``**``.
            tighter = (slot is not left) != isinstance(op, ast.Pow)
            return _BINARY[type(op)] + (1 if tighter else 0)
        case ast.BoolOp(op=ast.Or()):
            return 3
        case ast.BoolOp():
            return 4
        case ast.UnaryOp(op=ast.Not()):
            return 5
        case ast.UnaryOp():
            return 13
        case ast.Compare():
            return 7  # an unbracketed comparison would chain instead of nest
        case ast.Await():
            return 15
        case ast.Attribute():
            return 16
        case ast.Call(func=callee):
            return 16 if slot is callee else 1
        case ast.Subscript(value=receiver):
            return 16 if slot is receiver else 1
        case ast.IfExp(orelse=alternative):
            return 2 if slot is alternative else 3
        case ast.Lambda():
            return 2
        case _:
            return 1  # a bracketed slot, where only a bare comma is in danger
