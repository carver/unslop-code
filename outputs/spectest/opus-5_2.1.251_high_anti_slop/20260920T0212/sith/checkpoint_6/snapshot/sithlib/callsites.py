"""Typing an unannotated parameter from the calls its own module makes.

A function without annotations still says what it takes, indirectly: the
arguments its callers pass. Only the module holding the function is read, so
the answer stays as cheap as the rest of the analysis.
"""

import ast

from .classes import is_method
from .values import FunctionValue

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def argument_values(evaluator, binding, context):
    """The values passed for a parameter at the calls made in its own module."""
    function = binding.owner
    if not isinstance(function, _FUNCTIONS):
        return []
    return [
        value
        for call in _calls_to(evaluator, function, context)
        for argument in _arguments_for(call, binding.name, function, context.module)
        for value in evaluator.infer(argument, context.at(call))
    ]


def _calls_to(evaluator, function, context):
    """The calls of a module that reach one function, spelled however they are."""
    for node in ast.walk(context.module.tree):
        if isinstance(node, ast.Call) and _spells(node.func, function.name):
            called = evaluator.infer(node.func, context.at(node))
            if any(isinstance(value, FunctionValue) and value.node is function
                   for value in called):
                yield node


def _arguments_for(call, name, function, module):
    """The expressions one call passes for a parameter, by keyword or position."""
    named = [keyword.value for keyword in call.keywords if keyword.arg == name]
    if named:
        return named
    position = _position(function, name, module)
    return [call.args[position]] if 0 <= position < len(call.args) else []


def _position(function, name, module):
    """Which argument of a call binds a parameter; a receiver takes the first."""
    declared = [argument.arg for argument in function.args.posonlyargs + function.args.args]
    if name not in declared:
        return -1
    return declared.index(name) - (1 if is_method(module, function) else 0)


def _spells(node, name):
    """Whether an expression being called is written as `name`."""
    if isinstance(node, ast.Name):
        return node.id == name
    return isinstance(node, ast.Attribute) and node.attr == name
