"""Listing the names a file defines and searching for them across a project.

Neither question involves a cursor: they read the scope tree a file was parsed
into and report the bindings it holds.  What separates them is how deep they
look -- a search never descends into a function body, because a local variable
is of no use to anyone outside it.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .definitions import Definition
from .project import Analysis, Project
from .source import read


def defined(analysis: Analysis, all_scopes: bool) -> list[Definition]:
    """The names a file binds: its module level ones, or those of every scope."""
    scopes = analysis.module.scope.descendants() if all_scopes else [analysis.module.scope]
    found = [binding.definition() for scope in scopes for binding in scope.bindings]
    return _ordered(found)


def search(project: Project, query: str) -> list[Definition]:
    """The project definitions whose name contains ``query``, closest match first."""
    wanted = query.lower()
    found = [definition
             for path in project.sources()
             for definition in _declared(project.analyse(path, read(path)))
             if wanted in definition.name.lower()]
    return sorted(dict.fromkeys(found),
                  key=lambda entry: (_rank(entry.name, wanted), entry.module_path, entry.line))


def _declared(analysis: Analysis) -> Iterator[Definition]:
    """The names a module writes down: its own and its classes', never its locals.

    Imported names are left out: they are declared by the module they came
    from, which the search reaches on its own.
    """
    for scope in analysis.module.scope.descendants("class"):
        for binding in scope.bindings:
            if not binding.imported:
                yield binding.definition()


def _rank(name: str, query: str) -> int:
    """An exact match ranks above a prefix match, which ranks above any match."""
    lowered = name.lower()
    if lowered == query:
        return 0
    return 1 if lowered.startswith(query) else 2


def _ordered(definitions: Iterable[Definition]) -> list[Definition]:
    """Unique definitions in the order the file writes them."""
    unique = dict.fromkeys(definitions)
    return sorted(unique, key=lambda entry: (entry.line, entry.column))
