"""Turning a cursor position into a ranked list of completions."""

from __future__ import annotations

import builtins
import keyword
import os

from . import cursor, matching, scopes
from .modules import ModuleIndex
from .resolve import Resolver
from .source import SourceFile, parse_tolerant
from .symbols import KEYWORD, Symbol


def complete(path: str, line: int, col: int, fuzzy: bool = False) -> list[dict]:
    """Completions offered at `line`/`col` of `path`, already ordered."""
    source = SourceFile.load(path)
    source.validate(line, col)

    text = source.lines[line - 1]
    context = cursor.analyze(text, line, col)
    tree = scopes.build(parse_tolerant(source.lines, line))
    resolver = Resolver(tree, ModuleIndex(os.path.dirname(os.path.abspath(path))))
    scope = scopes.scope_at(tree, line, _indent_of(text, col))

    if context.is_attribute:
        candidates = _attribute_symbols(resolver, scope, context.receiver)
    else:
        candidates = _name_symbols(resolver, scope, line) + _keyword_symbols()
    return matching.select(candidates, context.prefix, fuzzy)


def _indent_of(text: str, col: int) -> int:
    """How far the cursor is indented, used to place a cursor on a blank line."""
    return col if not text[:col].strip() else len(text) - len(text.lstrip())


def _name_symbols(resolver: Resolver, scope: scopes.Scope, line: int) -> list[Symbol]:
    """Every bare name visible at the cursor, nearest binding shadowing the rest."""
    symbols = {
        name: resolver.symbol(binding)
        for name, binding in scopes.visible_bindings(scope, line).items()
    }
    for module in scopes.visible_star_imports(scope, line):
        handle = resolver.modules.resolve(module)
        for symbol in resolver.module_symbols(handle) if handle else []:
            symbols.setdefault(symbol.name, symbol)
    for symbol in _builtin_symbols():
        symbols.setdefault(symbol.name, symbol)
    return list(symbols.values())


def _attribute_symbols(resolver: Resolver, scope: scopes.Scope, receiver: str) -> list[Symbol]:
    """The attributes of the expression written before the dot, if it resolves."""
    target = resolver.source(receiver, scope)
    return target.attributes() if target else []


def _builtin_symbols() -> list[Symbol]:
    return [Symbol.from_object(name, getattr(builtins, name)) for name in dir(builtins)]


def _keyword_symbols() -> list[Symbol]:
    return [Symbol.of(name, KEYWORD) for name in keyword.kwlist]
