"""Wiring the pieces together into a single request."""

from __future__ import annotations

import ast
from pathlib import Path

from . import imports, inference
from .cursor import Reference, name_at
from .definitions import Definition, ordered
from .errors import SithError
from .imports import ImportContext
from .project import Analysis, ModuleInfo, Project
from .results import Completion, build_completions, builtin_symbols, keyword_symbols
from .scopes import Scope
from .source import SourceFile
from .values import Symbol, Value


def complete(path: Path, line: int, column: int, root: Path | None = None, *,
             fuzzy: bool = False) -> list[Completion]:
    """Completions offered at ``line``/``column`` of ``path``."""
    source, project, analysis = _analyse(path, root)
    context = source.context_at(line, column)
    scope = analysis.module.scope.innermost(line)

    if context.imports is not None:
        symbols = _import_symbols(project, analysis.info, context.imports)
    elif context.attribute:
        symbols = _attribute_symbols(context.receiver, scope, line)
    else:
        symbols = _name_symbols(scope, line)
    return build_completions(symbols, context.prefix, fuzzy)


def goto(path: Path, line: int, column: int, root: Path | None = None, *,
         follow: bool = False) -> list[Definition]:
    """Where the name at ``line``/``column`` of ``path`` was written down.

    ``follow`` reports the definition an imported name came from rather than
    the import statement that brought it into this file.
    """
    reference, scope = _reference(path, line, column, root)
    match reference.node:
        case ast.Attribute(value=receiver, attr=name):
            found = _attribute_sites(inference.infer(receiver, scope, line), name, follow)
        case _:
            found = [definition
                     for binding in scope.lookup(reference.name, line)
                     for definition in (binding.followed() if follow else [binding.definition()])]
    return ordered(found)


def infer(path: Path, line: int, column: int, root: Path | None = None) -> list[Definition]:
    """What the name at ``line``/``column`` of ``path`` evaluates to."""
    reference, scope = _reference(path, line, column, root)
    match reference.node:
        case ast.Name() | ast.Attribute():
            values = [inference.infer(reference.node, scope, line)]
        case _:
            values = [binding.value() for binding in scope.lookup(reference.name, line)]
    return ordered(definition for value in values for definition in value.definitions())


def _analyse(path: Path, root: Path | None) -> tuple[SourceFile, Project, Analysis]:
    """Load ``path`` and parse it as part of the project rooted at ``root``.

    Without an explicit root the project is the directory the file lives in,
    which is what makes a single file analysable on its own.
    """
    source = SourceFile.load(path)
    project = Project((root or path.parent).resolve())
    return source, project, project.analyse(path, source.text)


def _reference(path: Path, line: int, column: int,
               root: Path | None) -> tuple[Reference, Scope]:
    """The name the cursor is on, and the scope that line belongs to."""
    source, _, analysis = _analyse(path, root)
    source.validate(line, column)
    reference = name_at(analysis.tree, line, column)
    if reference is None:
        raise SithError(f"no name at line {line}, column {column}")
    return reference, analysis.module.scope.innermost(line)


def _attribute_sites(receiver: Value, name: str, follow: bool) -> list[Definition]:
    """Where an attribute of ``receiver`` was written, else what type it has."""
    found = receiver.symbol(name)
    if found is None:
        return []
    return found.origin() if follow else found.site()


def _attribute_symbols(receiver: ast.expr | None, scope: Scope, line: int) -> list[Symbol]:
    """Attributes of the expression before the dot; keywords never apply here."""
    if receiver is None:
        return []
    return inference.infer(receiver, scope, line).attributes()


def _import_symbols(project: Project, info: ModuleInfo,
                    context: ImportContext) -> list[Symbol]:
    """What the unfinished import statement under the cursor can name.

    The module path offers modules -- everything importable when nothing has
    been typed yet -- while the import clause offers the names inside the
    module the path picked out.
    """
    dotted = imports.absolute(context.module, context.level, info.package)
    if dotted is None:
        return []  # the import reaches above the project root
    if context.names:
        return project.importable(dotted)
    return project.modules(dotted) if dotted or context.level else project.top_level()


def _name_symbols(scope: Scope, line: int) -> list[Symbol]:
    """Names visible at ``line``, shadowing outwards, plus builtins and keywords."""
    visible = [Symbol(name, binding.value(), binding)
               for name, binding in scope.visible(line).items()]
    shadowed = {symbol.name for symbol in visible}
    builtin = [symbol for symbol in builtin_symbols() if symbol.name not in shadowed]
    return visible + builtin + keyword_symbols()
