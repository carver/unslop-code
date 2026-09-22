"""Inferring a parameter's type from the calls a file makes to its function.

A function with neither an annotation nor a stub still has a type its callers
agree on, so the arguments the file passes are read as if they were the
annotation.  Only this file is searched: what other modules pass is their own
business and would cost a project-wide scan to find.
"""

from __future__ import annotations

import ast

from . import params, scopes


def parameter_types(resolver, function: ast.AST, name: str) -> list:
    """What `name` is bound to at the calls this module makes to `function`."""
    position = params.positional_index(function.args, name)
    method = _is_method(resolver, function)
    found = []
    for call in _calls_to(resolver.tree.root.node, function.name):
        offset = 1 if method and isinstance(call.func, ast.Attribute) else 0
        passed = _argument(call, position, offset, name)
        if passed is not None:
            found.extend(resolver.expression(passed, _scope_of(resolver, call)))
    return found


def _calls_to(module: ast.Module, name: str) -> list[ast.Call]:
    """Every call in the module whose callee is written with that name."""
    return [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and _callee_name(node.func) == name
    ]


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _argument(call: ast.Call, position: int | None, offset: int, name: str) -> ast.expr | None:
    """The expression a call passes for one parameter, by keyword or by position."""
    keyed = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    if keyed is not None:
        return keyed
    if position is None or not 0 <= position - offset < len(call.args):
        return None
    return call.args[position - offset]


def _is_method(resolver, function: ast.AST) -> bool:
    scope = resolver.tree.scope_for(function)
    return scope is not None and scope.parent is not None and scope.parent.kind == "class"


def _scope_of(resolver, call: ast.Call) -> scopes.Scope:
    return scopes.scope_at(resolver.tree, call.lineno, call.col_offset)
