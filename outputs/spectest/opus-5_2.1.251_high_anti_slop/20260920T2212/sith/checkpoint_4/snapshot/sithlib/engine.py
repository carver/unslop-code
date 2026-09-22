"""Wiring the pieces together into a single request."""

from __future__ import annotations

import ast
from pathlib import Path

from . import calls, imports, inference, symbols
from .cursor import Reference, name_at
from .definitions import Definition, ordered
from .errors import SithError
from .imports import ImportContext
from .project import Analysis, ModuleInfo, Project
from .references import Occurrence, across_project, resolve, within_file
from .results import Completion, build_completions, builtin_symbols, keyword_symbols
from .scopes import Scope
from .signatures import SignatureHelp
from .source import SourceFile
from .values import Symbol


def complete(path: Path, line: int, column: int, root: Path | None = None, *,
             fuzzy: bool = False) -> list[Completion]:
    """Completions offered at ``line``/``column`` of ``path``."""
    source, project, analysis = _analyse(path, root)
    context = source.context_at(line, column)
    scope = analysis.module.scope.innermost(line)

    if context.imports is not None:
        found = _import_symbols(project, analysis.info, context.imports)
    elif context.attribute:
        found = _attribute_symbols(context.receiver, scope, line)
    else:
        found = _name_symbols(scope, line)
    return build_completions(found, context.prefix, fuzzy)


def goto(path: Path, line: int, column: int, root: Path | None = None, *,
         follow: bool = False) -> list[Definition]:
    """Where the name at ``line``/``column`` of ``path`` was written down.

    ``follow`` reports the definition an imported name came from rather than
    the import statement that brought it into this file.
    """
    source, _, analysis = _analyse(path, root)
    reference, scope = _reference(source, analysis, line, column)
    return ordered(resolve(reference, scope, line, follow))


def infer(path: Path, line: int, column: int, root: Path | None = None) -> list[Definition]:
    """What the name at ``line``/``column`` of ``path`` evaluates to."""
    source, _, analysis = _analyse(path, root)
    reference, scope = _reference(source, analysis, line, column)
    match reference.node:
        case ast.Name() | ast.Attribute():
            values = [inference.infer(reference.node, scope, line)]
        case _:
            values = [binding.value() for binding in scope.lookup(reference.name, line)]
    return ordered(definition for value in values for definition in value.definitions())


def signatures(path: Path, line: int, column: int,
               root: Path | None = None) -> list[SignatureHelp]:
    """The signatures of the call whose arguments are being written at the cursor.

    A cursor that is not inside a call's parentheses is not a failure; it
    simply has no signature to report.
    """
    source, _, analysis = _analyse(path, root)
    site = calls.call_at(source.text, source.offset(line, column))
    if site is None:
        return []
    scope = analysis.module.scope.innermost(site.line)
    declared = inference.infer(site.callee, scope, site.line).signatures()
    found = sorted(dict.fromkeys(declared),
                   key=lambda signature: (signature.module_path, signature.line))
    return [SignatureHelp(signature, signature.parameter(site.position, site.keyword))
            for signature in found]


def references(path: Path, line: int, column: int, root: Path | None = None, *,
               project_wide: bool = False) -> list[Occurrence]:
    """Where the name at ``line``/``column`` of ``path`` is written.

    Within one file every occurrence of the name counts; across the project
    only those resolving to the same symbol do, so that an unrelated name of
    the same spelling in another scope stays out.
    """
    source, project, analysis = _analyse(path, root)
    reference, scope = _reference(source, analysis, line, column)
    if project_wide:
        return across_project(project, reference, scope, line)
    return within_file(analysis, reference.name)


def search(query: str, root: Path) -> list[Definition]:
    """The names defined anywhere in the project that contain ``query``."""
    return symbols.search(Project(root.resolve()), query)


def names(path: Path, root: Path | None = None, *,
          all_scopes: bool = False) -> list[Definition]:
    """The names ``path`` defines, at module level or in every scope it holds."""
    _, _, analysis = _analyse(path, root)
    return symbols.defined(analysis, all_scopes)


def _analyse(path: Path, root: Path | None) -> tuple[SourceFile, Project, Analysis]:
    """Load ``path`` and parse it as part of the project rooted at ``root``.

    Without an explicit root the project is the directory the file lives in,
    which is what makes a single file analysable on its own.
    """
    source = SourceFile.load(path)
    project = Project((root or path.parent).resolve())
    return source, project, project.analyse(path, source.text)


def _reference(source: SourceFile, analysis: Analysis, line: int,
               column: int) -> tuple[Reference, Scope]:
    """The name the cursor is on, and the scope that line belongs to."""
    source.validate(line, column)
    reference = name_at(analysis.tree, line, column)
    if reference is None:
        raise SithError(f"no name at line {line}, column {column}")
    return reference, analysis.module.scope.innermost(line)


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
