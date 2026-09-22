"""Where a name leads and where else it is written.

Resolving a reference -- following the imports it came through until it reaches
the place it was really defined -- is what ``goto`` reports and what tells two
occurrences of the same spelling apart: a project-wide search keeps only the
ones that lead back to the definitions the cursor's name leads to.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from typing import Iterable, Iterator

from .cursor import Reference, all_names, defines
from .definitions import Definition
from .inference import infer
from .project import Analysis, Project
from .scopes import Scope
from .source import read


@dataclass(frozen=True)
class Occurrence:
    """One place a name is written, defining it or using it."""

    module_path: str
    line: int
    column: int
    is_definition: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve(reference: Reference, scope: Scope, line: int, follow: bool) -> list[Definition]:
    """The definitions ``reference`` names, read at ``line`` of ``scope``.

    ``follow`` chases the imports a name came through to where it was really
    written, rather than stopping at the import statement.
    """
    match reference.node:
        case ast.Attribute(value=receiver, attr=name):
            found = infer(receiver, scope, line).symbol(name)
            if found is None:
                return []
            return found.origin() if follow else found.site()
        case _:
            return [definition
                    for binding in scope.lookup(reference.name, line)
                    for definition in (binding.followed() if follow else [binding.definition()])]


def within_file(analysis: Analysis, name: str) -> list[Occurrence]:
    """Every place ``name`` is written in the one file under the cursor."""
    return _ordered(Occurrence(analysis.info.path, line, column, defines(found.node))
                    for line, column, found in all_names(analysis.tree)
                    if found.name == name)


def across_project(project: Project, reference: Reference, scope: Scope,
                   line: int) -> list[Occurrence]:
    """Every place in the project that names the very symbol under the cursor."""
    target = frozenset(resolve(reference, scope, line, follow=True))
    return _ordered(occurrence
                    for path in project.sources()
                    for occurrence in _matching(project.analyse(path, read(path)),
                                                reference.name, target))


def _matching(analysis: Analysis, name: str,
              target: frozenset[Definition]) -> Iterator[Occurrence]:
    """The occurrences of ``name`` in one file that lead back to ``target``."""
    module = analysis.module.scope
    for line, column, found in all_names(analysis.tree):
        if found.name != name:
            continue
        if target.intersection(resolve(found, module.innermost(line), line, follow=True)):
            yield Occurrence(analysis.info.path, line, column, defines(found.node))


def _ordered(occurrences: Iterable[Occurrence]) -> list[Occurrence]:
    """Unique occurrences by path, then line, then column."""
    unique = dict.fromkeys(occurrences)
    return sorted(unique, key=lambda entry: (entry.module_path, entry.line, entry.column))
