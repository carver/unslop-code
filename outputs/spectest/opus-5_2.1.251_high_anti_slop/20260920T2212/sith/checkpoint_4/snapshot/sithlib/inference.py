"""Inferring the value of an expression from its syntax."""

from __future__ import annotations

import ast
import builtins

from . import signatures
from .cursor import name_column
from .definitions import Definition
from .scopes import Scope
from .values import (
    UNKNOWN,
    Lazy,
    Param,
    SourceFunction,
    Value,
    runtime_instance,
    runtime_value,
    union,
)

_LITERAL_TYPES: dict[type[ast.AST], type] = {
    ast.JoinedStr: str,
    ast.List: list,
    ast.ListComp: list,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.Set: set,
    ast.SetComp: set,
    ast.Tuple: tuple,
}


def infer(node: ast.expr, scope: Scope, line: int) -> Value:
    """The value ``node`` evaluates to when read at ``line`` of ``scope``.

    The line matters because the branch a name is read in can narrow it.
    """
    literal = _LITERAL_TYPES.get(type(node))
    if literal is not None:
        return runtime_instance(literal)
    match node:
        case ast.Constant(value=value):
            return runtime_instance(type(value))
        case ast.Lambda():
            return _lambda(node, scope)
        case ast.Name(id=name):
            return lookup(name, scope, line)
        case ast.Attribute(value=parent, attr=attribute):
            return infer(parent, scope, line).attribute(attribute) or UNKNOWN
        case ast.Call(func=func):
            return infer(func, scope, line).instantiated()
        case ast.IfExp(body=body, orelse=orelse):
            return union([infer(body, scope, line), infer(orelse, scope, line)])
        case _:
            return UNKNOWN


def lookup(name: str, scope: Scope, line: int) -> Value:
    """Resolve a bare name through the scope chain, then through builtins.

    The branch the name is read in wins over the bindings it guards, and a
    parameter is unwrapped to whatever its annotation says it holds: the
    ``param`` kind describes the binding, not the object flowing out of it.
    """
    bound = [_held(binding.value()) for binding in scope.lookup(name, line)]
    value = union(bound) if bound else _builtin(name)
    narrowing = scope.narrowing(name, line)
    return narrowing.refine(value) if narrowing else value


def _held(value: Value) -> Value:
    return value.annotated if isinstance(value, Param) else value


def _builtin(name: str) -> Value:
    if hasattr(builtins, name):
        return runtime_value(getattr(builtins, name), name)
    return UNKNOWN


def _lambda(node: ast.Lambda, scope: Scope) -> SourceFunction:
    """A lambda has no name to report, but calling it still yields its body."""
    site = Definition("<lambda>", "function", "<lambda>", "", node.lineno,
                      name_column(node), "lambda")
    return SourceFunction(site, Lazy(lambda: infer(node.body, scope, node.lineno)),
                          signatures.from_lambda(node, ""))
