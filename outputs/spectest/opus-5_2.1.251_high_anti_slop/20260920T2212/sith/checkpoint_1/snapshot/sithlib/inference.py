"""Inferring the value of an expression from its syntax."""

from __future__ import annotations

import ast
import builtins

from .scopes import Scope
from .values import (
    UNKNOWN,
    Param,
    SourceClass,
    SourceFunction,
    SourceInstance,
    RuntimeObject,
    Value,
    runtime_instance,
    runtime_value,
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


def infer(node: ast.expr, scope: Scope) -> Value:
    """The value ``node`` evaluates to, as far as it can be determined."""
    literal = _LITERAL_TYPES.get(type(node))
    if literal is not None:
        return runtime_instance(literal)
    match node:
        case ast.Constant(value=value):
            return runtime_instance(type(value))
        case ast.Lambda():
            return SourceFunction("<lambda>")
        case ast.Name(id=name):
            return lookup(name, scope)
        case ast.Attribute(value=parent, attr=attribute):
            return infer(parent, scope).attribute(attribute) or UNKNOWN
        case ast.Call(func=func):
            return instantiate(infer(func, scope))
        case _:
            return UNKNOWN


def lookup(name: str, scope: Scope) -> Value:
    """Resolve a bare name through the scope chain, then through builtins.

    A parameter is unwrapped to whatever its annotation says it holds: the
    ``param`` kind describes the binding, not the object flowing out of it.
    """
    definition = scope.lookup(name)
    if definition is not None:
        value = definition.value()
        return value.annotated if isinstance(value, Param) else value
    if hasattr(builtins, name):
        return runtime_value(getattr(builtins, name), name)
    return UNKNOWN


def instantiate(value: Value) -> Value:
    """The value produced by calling ``value``."""
    match value:
        case SourceClass():
            return SourceInstance(value)
        case RuntimeObject(obj=obj, kind="class"):
            return runtime_instance(obj)
        case _:
            return UNKNOWN
