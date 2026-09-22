"""The `rename` subcommand.

Renaming a plain name rewrites every occurrence the project-wide `references`
search reports. A cursor on a module name is a different job: the file or
directory behind the module moves, and the import paths that spell it are
rewritten along with the local names those imports bind.
"""

from __future__ import annotations

from typing import Iterator, Optional

from .analysis import Analyzer, Scope, walk_scopes
from .edits import Edit, RefactorError, Refactoring, checked_identifier, rewrite
from .modules import import_edits, module_in_import, module_value, moved_path
from .navigation import BINDINGS, VALUES, Query
from .project import Project
from .references import identified_occurrences, project_occurrences, spelled
from .source import Source
from .stubs import source_half
from .symbols import Symbol


def rename(source: Source, project: Project, line: int, col: int, new_name: str, diff: bool) -> str:
    """Rename the name at the cursor everywhere the project writes it."""
    checked_identifier(new_name)
    written = module_in_import(source, project, line, col)
    if written is not None:
        return _renamed_module(project, written, new_name).report(diff)
    query = Query.at(source, project, line, col)
    module = _module_at(query)
    if module is not None:
        return _renamed_module(project, module, new_name).report(diff)
    return _renamed_name(project, query, new_name).report(diff)


def _module_at(query: Query) -> Optional[Analyzer]:
    """The module the name under the cursor stands for, if it is one."""
    value = VALUES[type(query.node)](query)
    return module_value(source_half(value)) if value is not None else None


def _renamed_name(project: Project, query: Query, new_name: str) -> Refactoring:
    """Rewrite every occurrence of the name the cursor sits on."""
    name = spelled(query.node)
    _reject_collision(query, new_name)
    edits = [
        rewrite(path, found.line, found.column, name, new_name)
        for path, found in project_occurrences(query, project, name)
    ]
    return Refactoring(project.root, edits)


def _renamed_module(project: Project, target: Analyzer, new_name: str) -> Refactoring:
    """Move a module's file and rewrite the imports and uses that name it."""
    old, new = moved_path(target.path, new_name)
    edits = list(import_edits(project, target, new_name))
    edits += _module_name_edits(project, target, new_name)
    return Refactoring(project.root, edits, [(old, new)])


def _module_name_edits(project: Project, target: Analyzer, new_name: str) -> Iterator[Edit]:
    """Rewrite the names bound to a module under the module's own spelling.

    `import pkg.inner` binds `pkg`, so only an import that binds the renamed
    module under its own name - and the uses of that binding - move with it.
    """
    leaf = target.module_name.split(".")[-1]
    identity = (target.module_path, "", "")
    for path in project.files():
        source = project.analyzer_at(path).source
        for found in identified_occurrences(project, source, leaf, identity):
            yield rewrite(path, found.line, found.column, leaf, new_name)


def _reject_collision(query: Query, new_name: str) -> None:
    """Refuse a rename that would land on a name already bound where it goes."""
    for symbol in BINDINGS[type(query.node)](query):
        scope = _binding_scope(symbol)
        if scope is None:
            continue
        taken = [other for other in symbol.origin.bindings(scope) if other.name == new_name]
        if taken:
            raise RefactorError(f"{new_name} is already defined in this scope")


def _binding_scope(symbol: Symbol) -> Optional[Scope]:
    """The scope a binding was made in, found by the symbol it produced."""
    analyzer = symbol.origin
    if analyzer is None:
        return None
    return next(
        (
            scope
            for scope in walk_scopes(analyzer.module_scope)
            if any(other is symbol for other in analyzer.bindings(scope))
        ),
        None,
    )
