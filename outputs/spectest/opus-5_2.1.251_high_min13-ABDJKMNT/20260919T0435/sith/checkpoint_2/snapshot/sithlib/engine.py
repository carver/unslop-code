"""Turning a cursor position into a ranked list of completions."""

from __future__ import annotations

import builtins
import keyword

from . import cursor, matching, scopes
from .analysis import Analysis
from .symbols import KEYWORD, Symbol


def complete(path: str, line: int, col: int, fuzzy: bool = False) -> list[dict]:
    """Completions offered at `line`/`col` of `path`, already ordered."""
    analysis = Analysis.at(path, line, col)
    context = cursor.analyze(analysis.line_text, line, col)

    if context.is_attribute:
        candidates = _attribute_symbols(analysis, context.receiver)
    else:
        candidates = _name_symbols(analysis) + _keyword_symbols()
    return matching.select(candidates, context.prefix, fuzzy)


def _name_symbols(analysis: Analysis) -> list[Symbol]:
    """Every bare name visible at the cursor, nearest binding shadowing the rest."""
    resolver = analysis.resolver
    symbols = {
        name: resolver.symbol(binding)
        for name, binding in scopes.visible_bindings(analysis.scope, analysis.line).items()
    }
    for module in scopes.visible_star_imports(analysis.scope, analysis.line):
        handle = resolver.modules.resolve(module)
        for symbol in resolver.module_symbols(handle) if handle else []:
            symbols.setdefault(symbol.name, symbol)
    for symbol in _builtin_symbols():
        symbols.setdefault(symbol.name, symbol)
    return list(symbols.values())


def _attribute_symbols(analysis: Analysis, receiver: str) -> list[Symbol]:
    """The attributes of the expression before the dot, merged over its possible types."""
    symbols: dict[str, Symbol] = {}
    for target in analysis.resolver.source(receiver, analysis.scope):
        for symbol in target.attributes():
            symbols.setdefault(symbol.name, symbol)
    return list(symbols.values())


def _builtin_symbols() -> list[Symbol]:
    return [Symbol.from_object(name, getattr(builtins, name)) for name in dir(builtins)]


def _keyword_symbols() -> list[Symbol]:
    return [Symbol.of(name, KEYWORD) for name in keyword.kwlist]
