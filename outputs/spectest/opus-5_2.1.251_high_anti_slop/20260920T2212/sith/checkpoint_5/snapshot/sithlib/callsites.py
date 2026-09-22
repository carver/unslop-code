"""Typing an unannotated parameter from the calls its own module makes.

A function written without annotations still says what it takes, indirectly:
the arguments its callers pass.  Only the module being analysed is searched --
how another file calls a function says nothing about how this one should be
read, and reading every file to answer one cursor would not be worth it.
"""

from __future__ import annotations

import ast
from typing import Iterator

from .inference import infer
from .scopes import Scope
from .signatures import Signature
from .values import Value, union


def parameter_type(tree: ast.Module, module: Scope, function: str, signature: Signature,
                   name: str) -> Value:
    """What the calls written in ``tree`` pass for parameter ``name``.

    Arguments line up with ``signature``, whose parameters are already free of
    the ``self`` a method call supplies through its receiver.
    """
    position = signature.position(name)
    return union([infer(argument, module.innermost(line), line)
                  for line, argument in _supplied(tree, function, position, name)])


def _supplied(tree: ast.Module, function: str, position: int,
              name: str) -> Iterator[tuple[int, ast.expr]]:
    """Every argument a call to ``function`` gives for one of its parameters."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called(node.func) != function:
            continue
        keyed = next((word.value for word in node.keywords if word.arg == name), None)
        if keyed is not None:
            yield node.lineno, keyed
        elif 0 <= position < len(node.args):
            yield node.lineno, node.args[position]


def _called(func: ast.expr) -> str:
    """The name a call writes, whether plainly or through an attribute."""
    match func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""
