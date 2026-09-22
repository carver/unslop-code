"""Wiring the pieces together into a single completion request."""

from __future__ import annotations

import ast
from pathlib import Path

from .inference import infer
from .parsing import tolerant_parse
from .project import Project
from .results import Completion, build_completions, builtin_symbols, keyword_symbols
from .scopes import Scope
from .source import SourceFile
from .values import Symbol


def complete(path: Path, line: int, column: int, fuzzy: bool) -> list[Completion]:
    """Completions offered at ``line``/``column`` of ``path``."""
    source = SourceFile.load(path)
    context = source.context_at(line, column)
    project = Project(path.parent.resolve())
    module = project.build(tolerant_parse(source.text), len(source.lines))
    scope = module.innermost(line)

    if context.attribute:
        symbols = _attribute_symbols(context.receiver, scope)
    else:
        symbols = _name_symbols(scope, line)
    return build_completions(symbols, context.prefix, fuzzy)


def _attribute_symbols(receiver: ast.expr | None, scope: Scope) -> list[Symbol]:
    """Attributes of the expression before the dot; keywords never apply here."""
    if receiver is None:
        return []
    return infer(receiver, scope).attributes()


def _name_symbols(scope: Scope, line: int) -> list[Symbol]:
    """Names visible at ``line``, shadowing outwards, plus builtins and keywords."""
    visible = [Symbol(name, definition.value())
               for name, definition in scope.visible(line).items()]
    shadowed = {symbol.name for symbol in visible}
    builtin = [symbol for symbol in builtin_symbols() if symbol.name not in shadowed]
    return visible + builtin + keyword_symbols()
