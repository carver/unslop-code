"""How tightly an expression binds, and where that forces parentheses.

Writing a variable's value where the variable stood is only safe while the
value binds at least as tightly as the place it lands in. These are the rules
`inline` consults before it wraps an expression it moves.
"""

from __future__ import annotations

import ast

ATOM = 16
"""Level of anything already delimited: a name, a literal, a call, a display."""

BINARY = {
    ast.BitOr: 7, ast.BitXor: 8, ast.BitAnd: 9, ast.LShift: 10, ast.RShift: 10,
    ast.Add: 11, ast.Sub: 11, ast.Mult: 12, ast.MatMult: 12, ast.Div: 12,
    ast.FloorDiv: 12, ast.Mod: 12, ast.Pow: 14,
}

COMPARISON, OR, AND, NOT, UNARY, AWAIT = 6, 3, 4, 5, 13, 15


def needs_parentheses(value: ast.expr, text: str, parent: ast.AST, node: ast.AST) -> bool:
    """Whether a value written in place of ``node`` has to be wrapped.

    A tuple written without brackets is always wrapped: its commas would
    otherwise join whatever list, call or assignment it is dropped into.
    """
    if isinstance(value, ast.Tuple) and not text.startswith("("):
        return True
    return level(value) < _required(parent, node)


def level(node: ast.AST) -> int:
    """How tightly an expression binds; higher binds tighter."""
    if isinstance(node, ast.BinOp):
        return BINARY[type(node.op)]
    if isinstance(node, ast.BoolOp):
        return OR if isinstance(node.op, ast.Or) else AND
    if isinstance(node, ast.UnaryOp):
        return NOT if isinstance(node.op, ast.Not) else UNARY
    return LEVELS.get(type(node), ATOM)


LEVELS = {
    ast.NamedExpr: 0,
    ast.Yield: 0,
    ast.YieldFrom: 0,
    ast.Lambda: 1,
    ast.IfExp: 2,
    ast.Tuple: 1,
    ast.Compare: COMPARISON,
    ast.Await: AWAIT,
    ast.Starred: UNARY,
}


def _required(parent: ast.AST, node: ast.AST) -> int:
    """The tightest binding a slot of ``parent`` accepts unparenthesised."""
    demand = DEMANDS.get(type(parent))
    return demand(parent, node) if demand is not None else 1


def _binary_demand(parent: ast.BinOp, node: ast.AST) -> int:
    """What an operand of a binary operator must bind at.

    The operand on the side the operator does not associate towards has to
    bind strictly tighter, or the rewritten code would regroup.
    """
    binding = BINARY[type(parent.op)]
    associates_left = not isinstance(parent.op, ast.Pow)
    on_far_side = (node is parent.right) if associates_left else (node is parent.left)
    return binding + 1 if on_far_side else binding


def _if_demand(parent: ast.IfExp, node: ast.AST) -> int:
    """A conditional's branches accept anything; its head has to bind past `or`."""
    return 1 if node is parent.orelse else OR


DEMANDS = {
    ast.BinOp: _binary_demand,
    ast.BoolOp: lambda parent, node: level(parent),
    ast.UnaryOp: lambda parent, node: level(parent),
    ast.Compare: lambda parent, node: COMPARISON + 1,
    ast.IfExp: _if_demand,
    ast.Attribute: lambda parent, node: ATOM,
    ast.Subscript: lambda parent, node: ATOM if node is parent.value else 1,
    ast.Call: lambda parent, node: ATOM if node is parent.func else 1,
    ast.Await: lambda parent, node: AWAIT,
    ast.Starred: lambda parent, node: UNARY,
}
