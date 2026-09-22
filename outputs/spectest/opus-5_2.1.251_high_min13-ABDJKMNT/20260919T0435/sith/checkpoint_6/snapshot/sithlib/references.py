"""The `references` command: every place a name is used or defined.

Two mentions of a name refer to the same thing when they lead to the same
definition, which is what keeps a project-wide search from collecting unrelated
names that merely happen to be spelled the same.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from . import cursor, definitions, project, scopes
from .analysis import Analysis
from .navigate import definitions_at
from .options import DEFAULT, Options
from .source import SithError

FILE = "file"
PROJECT = "project"

#: Contexts that write a name rather than read it.
_BINDING_CONTEXTS = (ast.Store, ast.Del)


@dataclass(frozen=True)
class Occurrence:
    """One written mention of a name."""

    module_path: str
    line: int
    column: int
    is_definition: bool

    @property
    def order(self) -> tuple[str, int, int]:
        return (self.module_path, self.line, self.column)

    def as_dict(self) -> dict:
        return {
            "module_path": self.module_path,
            "line": self.line,
            "column": self.column,
            "is_definition": self.is_definition,
        }


def references(path: str, line: int, col: int, scope: str = FILE, root: str | None = None,
               options: Options = DEFAULT) -> list[dict]:
    """Where the name at the cursor is referenced, within the file or the project."""
    analysis = Analysis.at(path, line, col, root, follow=True, options=options)
    reference = cursor.reference_at(analysis.line_text, col)
    if reference is None:
        raise SithError(f"no name at line {line}, column {col}")
    if reference.name is None:
        return []  # a literal is not a name, so nothing refers to it
    wanted = _places(definitions_at(analysis, reference))
    here = analysis.resolver.module.path
    found = _search(analysis.request, here, scope, reference.name, wanted)
    return [occurrence.as_dict() for occurrence in sorted(set(found), key=lambda o: o.order)]


def _search(request, module_path: str, scope: str, name: str, wanted: frozenset):
    """Scan the project, or only the file the cursor is in, for mentions of `name`."""
    modules = project.modules(
        request.root, follow=True, index=request.index(), settings=request.settings
    )
    for resolver, tree in modules:
        if scope == FILE and resolver.module.path != module_path:
            continue
        yield from _occurrences(resolver, tree, name, wanted)


def _occurrences(resolver, tree, name: str, wanted: frozenset):
    """The mentions of `name` in one module that refer to what the cursor refers to."""
    path = resolver.module.path
    for binding in _bindings(tree, name):
        column = definitions.name_column(resolver.module.lines, binding.node, name)
        if _refers(wanted, _places(resolver.binding_definitions([binding]))):
            yield Occurrence(path, binding.lineno, column, True)
    for node in ast.walk(tree.root.node):
        written = _written_at(resolver, node, name)
        if written and _refers(wanted, _places(_reached(resolver, tree, node))):
            yield Occurrence(path, *written, _is_binding(node))


def _bindings(tree, name: str) -> list[scopes.Binding]:
    """Every binding of `name` the module makes, in any of its scopes."""
    return [
        binding
        for scope in tree.by_node.values()
        for binding in scope.bindings
        if binding.name == name
    ]


def _written_at(resolver, node: ast.AST, name: str) -> tuple[int, int] | None:
    """Where a node mentions `name`, or None when it does not mention it at all.

    An attribute is written after the expression it hangs off, which is where
    the identifier is looked for rather than at the start of the whole node.
    """
    if isinstance(node, ast.Name) and node.id == name:
        return (node.lineno, node.col_offset)
    if not (isinstance(node, ast.Attribute) and node.attr == name):
        return None
    owner = node.value
    line = owner.end_lineno or owner.lineno
    lines = resolver.module.lines
    return (line, definitions.column_after(lines, line, owner.end_col_offset, name))


def _reached(resolver, tree, node: ast.AST) -> list:
    """Where the definition of a mention lies, resolved from where it is written."""
    scope = scopes.scope_at(tree, node.lineno, node.col_offset)
    if isinstance(node, ast.Name):
        return resolver.binding_definitions(resolver.bindings_for(node.id, scope))
    owners = resolver.expression(node.value, scope)
    return [record for owner in owners for record in owner.member_definitions(node.attr)]


def _is_binding(node: ast.AST) -> bool:
    return isinstance(getattr(node, "ctx", None), _BINDING_CONTEXTS)


def _places(found) -> frozenset:
    return frozenset((record.module_path, record.line, record.column) for record in found)


def _refers(wanted: frozenset, reached: frozenset) -> bool:
    """Whether a mention leads where the cursor's name leads.

    A name that resolves to nothing -- a builtin, or something the project does
    not define -- has no identity to compare, so its spelling is all there is.
    """
    return not wanted or not reached or bool(wanted & reached)
