"""Inferring parameter types from the calls a file makes.

A function written without annotations still says what its parameters hold if
the file goes on to call it, so the arguments written at those call sites are
resolved and offered as the parameter's type. Only the file the function is
written in is read; a call in another module does not describe it.
"""

from __future__ import annotations

import ast
from typing import Dict, Iterator, List, Optional, Set

from .runtime import Value, union

ARGUMENT_DEPTH = 1
"""Inference depth arguments are resolved at, which bounds recursive calls."""


def call_site_types(analyzer, node: ast.AST, receiver: bool) -> Dict[str, Optional[Value]]:
    """The types this file's calls to ``node`` pass to its parameters.

    ``receiver`` says that the first declared parameter is the ``self`` or
    ``cls`` a call never writes, so arguments start at the one after it.
    """
    positional = [argument.arg for argument in node.args.posonlyargs + node.args.args]
    named = set(positional) | {argument.arg for argument in node.args.kwonlyargs}
    passed: Dict[str, List[Optional[Value]]] = {}
    for call in _calls_to(analyzer.tree, node.name):
        for name, expression in _arguments(call, positional[1:] if receiver else positional, named):
            passed.setdefault(name, []).append(_value_of(analyzer, call, expression))
    return {name: union(values) for name, values in passed.items()}


def _calls_to(tree: ast.Module, name: str) -> Iterator[ast.Call]:
    """Calls written anywhere in a file whose callee is spelled ``name``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node.func) == name:
            yield node


def _callee(node: ast.expr) -> Optional[str]:
    """The name a call is written against, plain or after a dot."""
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _arguments(call: ast.Call, positional: List[str], named: Set[str]):
    """Each parameter one call site binds, with the expression bound to it."""
    yield from zip(positional, call.args)
    yield from (
        (keyword.arg, keyword.value) for keyword in call.keywords if keyword.arg in named
    )


def _value_of(analyzer, call: ast.Call, expression: ast.expr) -> Optional[Value]:
    """What an argument holds, read in the scope the call is written in."""
    scope = analyzer.scope_at(call.lineno, call.col_offset)
    return analyzer.resolve(expression, analyzer.lookup_from(scope), ARGUMENT_DEPTH)
