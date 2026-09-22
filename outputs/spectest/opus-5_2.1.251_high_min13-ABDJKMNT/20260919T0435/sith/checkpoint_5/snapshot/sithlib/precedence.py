"""Whether an expression needs brackets once it is written somewhere else.

Moving an expression into another one is only safe while the operators around
it still bind the way they did.  Each expression form is given the strength of
the grammar rule that produces it, and each place a child can sit is given the
strength that place demands; a child that binds more loosely than its new home
demands is bracketed.
"""

from __future__ import annotations

import ast

LAMBDA = 1
TERNARY = 2
OR = 3
AND = 4
NOT = 5
COMPARISON = 6
UNARY = 13
POWER = 14
AWAIT = 15
PRIMARY = 16
ATOM = 17

#: The strength of each binary operator, loosest first.
BINARY = {
    ast.BitOr: 7, ast.BitXor: 8, ast.BitAnd: 9, ast.LShift: 10, ast.RShift: 10,
    ast.Add: 11, ast.Sub: 11, ast.Mult: 12, ast.Div: 12, ast.FloorDiv: 12,
    ast.Mod: 12, ast.MatMult: 12, ast.Pow: POWER,
}

#: How tightly each place binds the child written in it.  A place that is not
#: listed cannot change what it holds -- a call argument, a list element, the
#: right-hand side of an assignment -- so anything may stand there unbracketed.
PLACES = {
    (ast.Attribute, "value"): PRIMARY,
    (ast.Subscript, "value"): PRIMARY,
    (ast.Call, "func"): PRIMARY,
    (ast.Await, "value"): PRIMARY,
    (ast.Starred, "value"): PRIMARY,
    (ast.Compare, "left"): BINARY[ast.BitOr],
    (ast.Compare, "comparators"): BINARY[ast.BitOr],
    (ast.IfExp, "test"): OR,
    (ast.IfExp, "body"): OR,
    (ast.IfExp, "orelse"): LAMBDA,
    (ast.Lambda, "body"): LAMBDA,
    (ast.comprehension, "iter"): OR,
    (ast.comprehension, "ifs"): OR,
}


def strength(node: ast.expr) -> int:
    """How tightly an expression holds itself together."""
    if isinstance(node, ast.BoolOp):
        return OR if isinstance(node.op, ast.Or) else AND
    if isinstance(node, ast.UnaryOp):
        return NOT if isinstance(node.op, ast.Not) else UNARY
    if isinstance(node, ast.BinOp):
        return BINARY[type(node.op)]
    return _FORMS.get(type(node), ATOM)


def demand(parent: ast.AST, field: str) -> int:
    """How tightly the place a child sits in binds it."""
    if isinstance(parent, ast.BinOp):
        return _operand_demand(parent, field)
    if isinstance(parent, ast.BoolOp):
        return strength(parent) + 1
    if isinstance(parent, ast.UnaryOp):
        return strength(parent)
    return PLACES.get((type(parent), field), 0)


def bracket(text: str, node: ast.expr, parent: ast.AST, field: str) -> str:
    """`text`, the source of `node`, bracketed if its new place binds tighter.

    A tuple written without brackets is always bracketed: its commas would
    otherwise be read as belonging to whatever holds it.  So is an expression
    written across several lines, which only holds together inside brackets.
    """
    if _bracketed(text):
        return text
    if isinstance(node, ast.Tuple) or "\n" in text or strength(node) < demand(parent, field):
        return f"({text})"
    return text


#: Expression forms whose strength is fixed rather than read off an operator.
_FORMS = {
    ast.Lambda: LAMBDA,
    ast.IfExp: TERNARY,
    ast.Compare: COMPARISON,
    ast.Await: AWAIT,
    ast.Call: PRIMARY,
    ast.Attribute: PRIMARY,
    ast.Subscript: PRIMARY,
    ast.NamedExpr: 0,
    ast.Yield: 0,
    ast.YieldFrom: 0,
    ast.Tuple: 0,
}


def _operand_demand(parent: ast.BinOp, field: str) -> int:
    """What an operand of a binary operator has to bind at.

    The operand on the side the operator does not associate with has to bind
    tighter than the operator itself, or the expression would regroup.  `**`
    associates to the right, and takes a unary operator there for free.
    """
    if isinstance(parent.op, ast.Pow):
        return UNARY if field == "right" else AWAIT
    return BINARY[type(parent.op)] + (1 if field == "right" else 0)


def _bracketed(text: str) -> bool:
    """Whether the source already wraps the whole expression in brackets."""
    if not text.startswith("("):
        return False
    depth = 0
    for index, character in enumerate(text):
        depth += (character == "(") - (character == ")")
        if depth == 0:
            return index == len(text) - 1
    return False
