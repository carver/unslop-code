"""Wiring the pieces together into a single request."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator

from . import inference
from .cursor import Reference, name_at
from .definitions import Definition, ordered
from .errors import SithError
from .project import Analysis, Project
from .results import Completion, build_completions, builtin_symbols, keyword_symbols
from .scopes import Scope
from .source import SourceFile
from .values import Symbol, Value


def complete(path: Path, line: int, column: int, fuzzy: bool) -> list[Completion]:
    """Completions offered at ``line``/``column`` of ``path``."""
    source, analysis = _analyse(path)
    context = source.context_at(line, column)
    scope = analysis.module.scope.innermost(line)

    if context.attribute:
        symbols = _attribute_symbols(context.receiver, scope, line)
    else:
        symbols = _name_symbols(scope, line)
    return build_completions(symbols, context.prefix, fuzzy)


def goto(path: Path, line: int, column: int) -> list[Definition]:
    """Where the name at ``line``/``column`` of ``path`` was written down."""
    reference, scope = _reference(path, line, column)
    match reference.node:
        case ast.Attribute(value=receiver, attr=name):
            found = _attribute_sites(inference.infer(receiver, scope, line), name)
        case _:
            found = [binding.definition() for binding in scope.lookup(reference.name, line)]
    return ordered(found)


def infer(path: Path, line: int, column: int) -> list[Definition]:
    """What the name at ``line``/``column`` of ``path`` evaluates to."""
    reference, scope = _reference(path, line, column)
    match reference.node:
        case ast.Name() | ast.Attribute():
            values = [inference.infer(reference.node, scope, line)]
        case _:
            values = [binding.value() for binding in scope.lookup(reference.name, line)]
    return ordered(definition for value in values for definition in value.definitions())


def _analyse(path: Path) -> tuple[SourceFile, Analysis]:
    source = SourceFile.load(path)
    project = Project(path.parent.resolve())
    return source, project.analyse(path, path.stem, source.text)


def _reference(path: Path, line: int, column: int) -> tuple[Reference, Scope]:
    """The name the cursor is on, and the scope that line belongs to."""
    source, analysis = _analyse(path)
    source.validate(line, column)
    reference = name_at(analysis.tree, line, column)
    if reference is None:
        raise SithError(f"no name at line {line}, column {column}")
    return reference, analysis.module.scope.innermost(line)


def _attribute_sites(receiver: Value, name: str) -> Iterator[Definition]:
    """Where an attribute of ``receiver`` was written, else what type it has."""
    for symbol in receiver.attributes():
        if symbol.name == name:
            yield from [symbol.site] if symbol.site else symbol.value.definitions()


def _attribute_symbols(receiver: ast.expr | None, scope: Scope, line: int) -> list[Symbol]:
    """Attributes of the expression before the dot; keywords never apply here."""
    if receiver is None:
        return []
    return inference.infer(receiver, scope, line).attributes()


def _name_symbols(scope: Scope, line: int) -> list[Symbol]:
    """Names visible at ``line``, shadowing outwards, plus builtins and keywords."""
    visible = [Symbol(name, binding.value(), binding.definition())
               for name, binding in scope.visible(line).items()]
    shadowed = {symbol.name for symbol in visible}
    builtin = [symbol for symbol in builtin_symbols() if symbol.name not in shadowed]
    return visible + builtin + keyword_symbols()
