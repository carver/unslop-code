"""Static guesses at the type a value expression produces."""

import ast
import inspect

from . import symbols
from .runtime import resolve_expression

_LITERAL_TYPES = {
    ast.List: "list",
    ast.ListComp: "list",
    ast.Dict: "dict",
    ast.DictComp: "dict",
    ast.Set: "set",
    ast.SetComp: "set",
    ast.Tuple: "tuple",
    ast.GeneratorExp: "generator",
    ast.JoinedStr: "str",
}


def type_name(node, index):
    """Name of the type `node` evaluates to, or ``None`` when out of reach."""
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    if isinstance(node, ast.Call):
        return _constructed_type(node.func, index)
    return _LITERAL_TYPES.get(type(node))


def assignment_symbol(name, value, lineno, index, annotation=None):
    """The symbol an assignment binds: an instance when typed, a statement otherwise."""
    resolved = type_name(value, index) or _annotation_name(annotation)
    if resolved is None:
        return symbols.statement(name, lineno)
    return symbols.instance(name, resolved, lineno)


def _constructed_type(func, index):
    """The class a call constructs, for calls that can be followed to a class."""
    if isinstance(func, ast.Name) and func.id in index.classes:
        return func.id
    obj = resolve_expression(func, index.lookup)
    return obj.__name__ if inspect.isclass(obj) else None


def _annotation_name(annotation):
    return annotation.id if isinstance(annotation, ast.Name) else None
