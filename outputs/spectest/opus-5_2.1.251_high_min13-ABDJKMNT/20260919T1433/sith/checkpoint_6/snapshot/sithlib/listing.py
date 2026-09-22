"""Listing definitions: the names a file declares and the ones a project holds.

Both `names` and `search` report the same records `goto` reports, so both are
built from the bindings the analyzer already makes; they differ in which
scopes they read and in how the answer is ordered.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Iterator, Tuple

from .analysis import CLASS_SCOPE, FUNCTION_SCOPE, MODULE_SCOPE, Analyzer, walk_scopes
from .definitions import Definition, document
from .importing import IMPORT_NODES
from .project import Project
from .source import Source

ALL_SCOPES = (MODULE_SCOPE, CLASS_SCOPE, FUNCTION_SCOPE)
DECLARING = (MODULE_SCOPE, CLASS_SCOPE)
"""Scopes `search` reads: a function body holds locals, which it does not."""

EXACT, PREFIX, SUBSTRING = range(3)


def names(source: Source, project: Project, all_scopes: bool) -> str:
    """The names a file defines, as a JSON document."""
    analyzer = project.analyzer_for(source)
    scopes = ALL_SCOPES if all_scopes else (MODULE_SCOPE,)
    listed = sorted(
        declared(analyzer, scopes, imports=True),
        key=lambda definition: (definition.line, definition.column),
    )
    entries = [{**asdict(definition), "is_definition": True} for definition in listed]
    return document(names=entries, definitions=entries)


def search(project: Project, query: str) -> str:
    """The definitions across a project whose name matches a query."""
    found = [
        definition
        for path in project.files()
        for definition in declared(project.analyzer_at(path), DECLARING, imports=False)
        if query.lower() in definition.name.lower()
    ]
    ranked = sorted(
        found,
        key=lambda definition: (
            _rank(query, definition.name), definition.module_path, definition.line
        ),
    )
    results = [_without_docstring(definition) for definition in ranked]
    return document(definitions=results, results=results)


def declared(analyzer: Analyzer, scopes: Tuple[str, ...], imports: bool) -> Iterator[Definition]:
    """The definitions bound in the chosen scopes of one file."""
    for scope in walk_scopes(analyzer.module_scope):
        if scope.kind not in scopes:
            continue
        for symbol in analyzer.bindings(scope):
            if imports or not isinstance(symbol.node, IMPORT_NODES):
                yield analyzer.binding_definition(symbol)


def _rank(query: str, name: str) -> int:
    """Search ordering: exact matches first, then prefixes, then substrings."""
    written, wanted = name.lower(), query.lower()
    if written == wanted:
        return EXACT
    return PREFIX if written.startswith(wanted) else SUBSTRING


def _without_docstring(definition: Definition) -> Dict:
    """A definition as a search result, which leaves the docstring out."""
    fields = asdict(definition)
    del fields["docstring"]
    return fields
