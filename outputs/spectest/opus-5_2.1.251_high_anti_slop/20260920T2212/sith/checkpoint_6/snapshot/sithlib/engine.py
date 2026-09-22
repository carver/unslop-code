"""Wiring the pieces together into a single request."""

from __future__ import annotations

import ast
import keyword
from pathlib import Path

from . import calls, contexts, extraction, imports, inference, inlining, moves, renaming, symbols
from .contexts import ScopeContext
from .cursor import Reference, name_at
from .definitions import Definition, ordered
from .diagnostics import Diagnostic, diagnose
from .edits import Refactoring
from .errors import SithError
from .imports import ImportContext
from .options import DEFAULTS, Options
from .project import Analysis, ModuleInfo, Project
from .references import Occurrence, across_project, resolve, within_file
from .results import Completion, build_completions, builtin_symbols, keyword_symbols
from .scopes import Scope
from .signatures import SignatureHelp
from .source import SourceFile
from .trees import Span
from .values import Symbol


def complete(path: Path, line: int, column: int, root: Path | None = None, *,
             fuzzy: bool = False, options: Options = DEFAULTS) -> list[Completion]:
    """Completions offered at ``line``/``column`` of ``path``."""
    source, project, analysis = _analyse(path, root, options)
    context = source.context_at(line, column)
    scope = analysis.module.scope.innermost(line)

    if context.imports is not None:
        found = _import_symbols(project, analysis.info, context.imports)
    elif context.attribute:
        found = _attribute_symbols(context.receiver, scope, line)
    else:
        found = _name_symbols(scope, line, options)
    return build_completions(found, context.prefix, fuzzy, options.settings)


def goto(path: Path, line: int, column: int, root: Path | None = None, *,
         follow: bool = False, options: Options = DEFAULTS) -> list[Definition]:
    """Where the name at ``line``/``column`` of ``path`` was written down.

    ``follow`` reports the definition an imported name came from rather than
    the import statement that brought it into this file.  A bare name the
    source never writes may still be one a live namespace holds.
    """
    source, _, analysis = _analyse(path, root, options)
    reference, scope = _reference(source, analysis, line, column)
    found = ordered(resolve(reference, scope, line, follow))
    if found or not isinstance(reference.node, ast.Name):
        return found
    return _runtime_definitions(reference.name, options)


def infer(path: Path, line: int, column: int, root: Path | None = None, *,
          options: Options = DEFAULTS) -> list[Definition]:
    """What the name at ``line``/``column`` of ``path`` evaluates to."""
    source, _, analysis = _analyse(path, root, options)
    reference, scope = _reference(source, analysis, line, column)
    match reference.node:
        case ast.Name() | ast.Attribute():
            values = [inference.infer(reference.node, scope, line)]
        case _:
            values = [binding.value() for binding in scope.lookup(reference.name, line)]
    return ordered(definition for value in values for definition in value.definitions())


def signatures(path: Path, line: int, column: int, root: Path | None = None, *,
               options: Options = DEFAULTS) -> list[SignatureHelp]:
    """The signatures of the call whose arguments are being written at the cursor.

    A cursor that is not inside a call's parentheses is not a failure; it
    simply has no signature to report.
    """
    source, _, analysis = _analyse(path, root, options)
    site = calls.call_at(source.text, source.offset(line, column))
    if site is None:
        return []
    scope = analysis.module.scope.innermost(site.line)
    declared = inference.infer(site.callee, scope, site.line).signatures()
    found = sorted(dict.fromkeys(declared),
                   key=lambda signature: (signature.module_path, signature.line))
    return [SignatureHelp(signature, signature.parameter(site.position, site.keyword))
            for signature in found]


def context(path: Path, line: int, column: int, root: Path | None = None, *,
            options: Options = DEFAULTS) -> list[ScopeContext]:
    """The classes and functions ``line`` of ``path`` is written inside."""
    source, _, analysis = _analyse(path, root, options)
    source.validate(line, column)
    return contexts.enclosing(analysis.tree, line)


def references(path: Path, line: int, column: int, root: Path | None = None, *,
               project_wide: bool = False, options: Options = DEFAULTS) -> list[Occurrence]:
    """Where the name at ``line``/``column`` of ``path`` is written.

    Within one file every occurrence of the name counts; across the project
    only those resolving to the same symbol do, so that an unrelated name of
    the same spelling in another scope stays out.
    """
    source, project, analysis = _analyse(path, root, options)
    reference, scope = _reference(source, analysis, line, column)
    if project_wide:
        return across_project(project, reference, scope, line)
    return within_file(analysis, reference.name)


def rename(path: Path, line: int, column: int, root: Path | None = None, *,
           new_name: str, options: Options = DEFAULTS) -> Refactoring:
    """Rename the name at ``line``/``column`` of ``path`` throughout the project.

    A cursor on a module renames the file or the directory it lives in, and
    restates the imports that name it; anything else is renamed wherever the
    project writes it.
    """
    _validate_name(new_name)
    source, project, analysis = _analyse(path, root, options)
    source.validate(line, column)
    dotted = moves.module_at(project, analysis, line, column)
    if dotted is not None:
        return moves.rename_module(project, dotted, new_name)
    reference, scope = _reference(source, analysis, line, column)
    return renaming.rename(project, reference, scope, line, new_name)


def inline(path: Path, line: int, column: int, root: Path | None = None, *,
           options: Options = DEFAULTS) -> Refactoring:
    """Replace the variable at ``line``/``column`` of ``path`` with its value."""
    source, _, analysis = _analyse(path, root, options)
    reference, scope = _reference(source, analysis, line, column)
    return inlining.inline(analysis, source, reference, scope, line)


def extract_variable(path: Path, line: int, column: int, root: Path | None = None, *,
                     until: tuple[int, int], name: str,
                     options: Options = DEFAULTS) -> Refactoring:
    """Extract the expression selected in ``path`` into a variable named ``name``."""
    _validate_name(name)
    source, _, analysis = _analyse(path, root, options)
    selection = _selection(source, line, column, until)
    return extraction.extract_variable(analysis, source, selection, name)


def extract_function(path: Path, line: int, column: int, root: Path | None = None, *,
                     until: tuple[int, int], name: str,
                     options: Options = DEFAULTS) -> Refactoring:
    """Extract the statements selected in ``path`` into a function named ``name``."""
    _validate_name(name)
    source, _, analysis = _analyse(path, root, options)
    selection = _selection(source, line, column, until)
    return extraction.extract_function(analysis, source, selection, name)


def errors(path: Path) -> list[Diagnostic]:
    """The syntax errors ``path`` holds; finding some is not a failure."""
    return diagnose(SourceFile.load(path).text)


def search(query: str, root: Path, *, options: Options = DEFAULTS) -> list[Definition]:
    """The names defined anywhere in the project that contain ``query``."""
    return symbols.search(Project(root.resolve(), options), query)


def names(path: Path, root: Path | None = None, *, all_scopes: bool = False,
          options: Options = DEFAULTS) -> list[Definition]:
    """The names ``path`` defines, at module level or in every scope it holds."""
    _, _, analysis = _analyse(path, root, options)
    return symbols.defined(analysis, all_scopes)


def _analyse(path: Path, root: Path | None,
             options: Options) -> tuple[SourceFile, Project, Analysis]:
    """Load ``path`` and parse it as part of the project rooted at ``root``.

    Without an explicit root the project is the directory the file lives in,
    which is what makes a single file analysable on its own.
    """
    source = SourceFile.load(path)
    project = Project((root or path.parent).resolve(), options)
    return source, project, project.analyse(path, source.text)


def _runtime_definitions(name: str, options: Options) -> list[Definition]:
    """What the live namespaces say ``name`` is, when they hold it at all."""
    value = options.namespaces.value(name) if options.namespaces is not None else None
    return value.definitions() if value is not None else []


def _validate_name(name: str) -> None:
    """Refuse anything that could not be written down as a name."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SithError(f"not a valid Python identifier: {name}")


def _selection(source: SourceFile, line: int, column: int,
               until: tuple[int, int]) -> Span:
    """The region between the cursor and ``--until``, both of which must exist."""
    source.validate(line, column)
    source.validate(*until)
    return Span(line, column, *until)


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


def _name_symbols(scope: Scope, line: int, options: Options) -> list[Symbol]:
    """Names visible at ``line``, shadowing outwards, plus builtins and keywords.

    Interpreter mode adds what the live namespaces hold, which the source
    itself has priority over: a name both know is reported as it was written.
    """
    visible = [Symbol(name, binding.value(), binding)
               for name, binding in scope.visible(line).items()]
    shadowed = {symbol.name for symbol in visible}
    builtin = [symbol for symbol in builtin_symbols() if symbol.name not in shadowed]
    offered = shadowed.union(symbol.name for symbol in builtin)
    live = options.namespaces.symbols() if options.namespaces is not None else []
    runtime = [symbol for symbol in live if symbol.name not in offered]
    return visible + builtin + runtime + keyword_symbols()
