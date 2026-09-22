"""Turning a cursor position into a ranked list of completions."""

from __future__ import annotations

import builtins
import keyword

from . import cursor, imports, matching, scopes
from .analysis import Analysis
from .options import DEFAULT, Options
from .symbols import KEYWORD, MODULE, Symbol


def complete(path: str, line: int, col: int, fuzzy: bool = False, project: str | None = None,
             options: Options = DEFAULT) -> list[dict]:
    """Completions offered at `line`/`col` of `path`, already ordered."""
    analysis = Analysis.at(path, line, col, project, options=options)
    settings = analysis.settings
    imported = cursor.import_at(analysis.line_text, col)
    if imported is not None:
        candidates = _import_symbols(analysis, imported)
        return matching.select(candidates, imported.prefix, fuzzy, settings)

    context = cursor.analyze(analysis.line_text, line, col)
    if context.is_attribute:
        candidates = _attribute_symbols(analysis, context.receiver)
    else:
        candidates = _name_symbols(analysis) + _keyword_symbols()
    return matching.select(candidates, context.prefix, fuzzy, settings)


def _name_symbols(analysis: Analysis) -> list[Symbol]:
    """Every bare name visible at the cursor, nearest binding shadowing the rest.

    Names the file itself explains come first: a namespace only contributes the
    ones static analysis never found.
    """
    resolver = analysis.resolver
    symbols = {
        name: resolver.symbol(binding)
        for name, binding in scopes.visible_bindings(analysis.scope, analysis.line).items()
    }
    for module, level in scopes.visible_star_imports(analysis.scope, analysis.line):
        handle = resolver.module_handle(module, level)
        for symbol in resolver.module_exports(handle) if handle else []:
            symbols.setdefault(symbol.name, symbol)
    for symbol in _builtin_symbols() + analysis.namespaces.symbols():
        symbols.setdefault(symbol.name, symbol)
    return list(symbols.values())


def _attribute_symbols(analysis: Analysis, receiver: str) -> list[Symbol]:
    """The attributes of the expression before the dot, merged over its possible types.

    A receiver static analysis knows nothing about may still be a live value,
    whose attributes the namespaces list.
    """
    symbols: dict[str, Symbol] = {}
    for target in analysis.resolver.source(receiver, analysis.scope):
        for symbol in target.attributes():
            symbols.setdefault(symbol.name, symbol)
    return list(symbols.values()) or analysis.namespaces.attributes(receiver)


def _import_symbols(analysis: Analysis, context: cursor.ImportContext) -> list[Symbol]:
    """What can follow the cursor in an import: a module name, or a module's names."""
    resolver = analysis.resolver
    if context.members:
        handle = resolver.module_handle(context.module, context.level)
        return resolver.module_exports(handle) if handle else []
    return [Symbol.of(name, MODULE) for name in _module_names(analysis, context)]


def _module_names(analysis: Analysis, context: cursor.ImportContext) -> list[str]:
    """The module names offered for a partially typed import path."""
    index = analysis.resolver.modules
    if not context.module and context.level == 0:
        return index.top_level()
    package = imports.absolute(analysis.resolver.module, context.level, context.module)
    if package is None:
        return []
    return index.submodules(package) if package else index.project_modules()


def _builtin_symbols() -> list[Symbol]:
    return [Symbol.from_object(name, getattr(builtins, name)) for name in dir(builtins)]


def _keyword_symbols() -> list[Symbol]:
    return [Symbol.of(name, KEYWORD) for name in keyword.kwlist]
