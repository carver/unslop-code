"""The `search` and `names` commands: definitions found by name and by file.

`search` reads the whole project but only the names a reader could import or
reach through a class, so local variables stay out of it.  `names` reads one
file and answers with what it declares.
"""

from __future__ import annotations

import os

from . import project, scopes
from .analysis import Analysis

#: How well a name answers a query; lower sorts first.
EXACT, PREFIX, SUBSTRING = range(3)

#: The binding forms a project-wide search offers: definitions, not imports.
SEARCHABLE = (scopes.DEF, scopes.CLASS, scopes.ASSIGN, scopes.TARGET)


def search(query: str, root: str | None = None) -> list[dict]:
    """The definitions across the project whose names contain `query`."""
    found = [
        (_ranked(query, binding.name), resolver.binding_definition(binding))
        for resolver, tree in project.modules(os.path.abspath(root or os.curdir))
        for binding in _searchable(tree.root)
        if query.lower() in binding.name.lower()
    ]
    ordered = sorted(dict.fromkeys(found), key=lambda pair: (pair[0], pair[1].order))
    return [record.as_dict(docstring=False) for _, record in ordered]


def names(path: str, all_scopes: bool = False, root: str | None = None) -> list[dict]:
    """Every name a file defines, at module level or in every scope."""
    analysis = Analysis.at(path, 1, 0, root)
    resolver, tree = analysis.resolver, analysis.tree
    scoped = tree.by_node.values() if all_scopes else [tree.root]
    found = [
        resolver.binding_definition(binding) for scope in scoped for binding in scope.bindings
    ]
    unique = sorted(dict.fromkeys(found), key=lambda record: (record.line, record.column))
    return [{**record.as_dict(), "is_definition": True} for record in unique]


def _searchable(scope: scopes.Scope):
    """The bindings written at module or class level; a function body is private."""
    yield from (binding for binding in scope.bindings if binding.form in SEARCHABLE)
    for child in scope.children:
        if child.kind == "class":
            yield from _searchable(child)


def _ranked(query: str, name: str) -> int:
    """How closely a name answers the query: exactly, by prefix, or anywhere."""
    lowered, target = query.lower(), name.lower()
    if target == lowered:
        return EXACT
    return PREFIX if target.startswith(lowered) else SUBSTRING
