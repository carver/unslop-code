"""Finding every place a name is written.

An occurrence is any spelling of the name: a use, a definition, a parameter
or an import. Searching one file takes the name at face value; searching the
project resolves each occurrence first, so that a name spelled the same way
in an unrelated scope is left out.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

from .analysis import SourceModule
from .definitions import document
from .following import resolved
from .importing import bound_name
from .navigation import BINDINGS, SPANS, Query
from .project import Project
from .source import Source
from .stubs import source_half
from .symbols import Symbol

FILE, PROJECT = "file", "project"

Identity = Tuple[str, str, str]
"""What a binding refers to: its module, its enclosing definitions, its name."""


@dataclass(frozen=True)
class Reference:
    """One place a name is written."""

    module_path: str
    line: int
    column: int
    is_definition: bool


def references(source: Source, project: Project, line: int, col: int, scope: str) -> str:
    """Every occurrence of the name at the cursor, as a JSON document."""
    query = Query.at(source, project, line, col)
    name = spelled(query.node)
    searched = _project_sources(project) if scope == PROJECT else [source]
    wanted = _identities(query) if scope == PROJECT else None
    found = {  # a set: one position is one reference, however many nodes cover it
        reference
        for target in searched
        for reference in _occurrences(project, target, name, wanted)
    }
    return document(references=[asdict(reference) for reference in sorted(found, key=_position)])


def project_occurrences(query: Query, project: Project, name: str) -> List[Tuple[Path, Reference]]:
    """Every place in the project that writes the name a query found.

    The refactoring commands rewrite exactly what `references --scope project`
    reports, so they share its search and keep the file each hit lies in.
    """
    wanted = _identities(query)
    return [
        (target.path, reference)
        for target in _project_sources(project)
        for reference in _occurrences(project, target, name, wanted)
    ]


def identified_occurrences(
    project: Project, source: Source, name: str, identity: Identity
) -> List[Reference]:
    """Occurrences of a name in one file that all refer to one symbol."""
    return list(_occurrences(project, source, name, {identity}))


def _position(reference: Reference):
    """Sort key: module path, then line, then column."""
    return reference.module_path, reference.line, reference.column


def _project_sources(project: Project) -> List[Source]:
    """Every project file, as the analysis of it already read them."""
    return [project.analyzer_at(path).source for path in project.files()]


def _occurrences(
    project: Project, source: Source, name: str, wanted: Optional[Set[Identity]]
) -> Iterator[Reference]:
    """Where a name is written in one file, filtered by what it refers to."""
    module_path = project.analyzer_for(source).module_path
    for node in ast.walk(source.tree):
        if spelled(node) != name:
            continue
        line, column, _ = SPANS[type(node)](node, source.lines)
        if wanted is None or wanted & _identities_at(source, project, line, column):
            yield Reference(module_path, line, column, is_definition(node))


def spelled(node: ast.AST) -> Optional[str]:
    """The name an occurrence writes, or ``None`` for nodes that write none."""
    reader = SPELLINGS.get(type(node))
    return reader(node) if reader is not None else None


SPELLINGS = {
    ast.Name: lambda node: node.id,
    ast.Attribute: lambda node: node.attr,
    ast.FunctionDef: lambda node: node.name,
    ast.AsyncFunctionDef: lambda node: node.name,
    ast.ClassDef: lambda node: node.name,
    ast.arg: lambda node: node.arg,
    ast.alias: bound_name,
}


def is_definition(node: ast.AST) -> bool:
    """Whether an occurrence is one that binds the name.

    Definitions, parameters and imports always bind; a plain name or
    attribute binds only where it is assigned to.
    """
    if isinstance(node, (ast.Name, ast.Attribute)):
        return isinstance(node.ctx, (ast.Store, ast.Del))
    return True


# --------------------------------------------------------------------------
# Symbol identity
# --------------------------------------------------------------------------


def _identities_at(source: Source, project: Project, line: int, column: int) -> Set[Identity]:
    """What the name written at a position refers to."""
    return _identities(Query.at(source, project, line, column))


def _identities(query: Query) -> Set[Identity]:
    """What the name a query found can refer to, one identity per binding."""
    found = (_identity(symbol) for symbol in BINDINGS[type(query.node)](query))
    return {identity for identity in found if identity is not None}


def _identity(symbol: Symbol) -> Optional[Identity]:
    """The symbol a binding ultimately names.

    Imports are walked through first, so a name imported into another file
    shares the identity of the definition it was imported from. A module
    stands for itself, whichever name a file imports it under.
    """
    reached = resolved(symbol)
    module = source_half(reached.value)
    if isinstance(module, SourceModule):
        return (module.analyzer.module_path, "", "")
    if reached.origin is None:
        return None
    return (reached.origin.module_path, reached.qualifier, reached.name)
