"""The `rename` command: one name, rewritten everywhere it is written."""

from __future__ import annotations

from . import definitions, moves, project, references, scopes
from .edits import Buffer, Workspace
from .refactor import at_cursor, identifier
from .source import SithError, parse_tolerant


def rename(path: str, line: int, col: int, new_name: str, root: str | None = None,
           diff: bool = False) -> dict | str:
    """Rename what the cursor rests on, along with every reference to it."""
    identifier(new_name)
    root = project.root_of(path, root)
    analysis, reference = at_cursor(path, line, col, root)
    workspace = Workspace(root)
    module = moves.module_at(analysis, reference, col, root)
    if module is not None:
        moves.rename_module(workspace, module, new_name)
    else:
        _rename_name(workspace, path, line, col, reference.name, new_name)
    return workspace.answer(diff)


def _rename_name(workspace: Workspace, path: str, line: int, col: int, old: str,
                 new: str) -> None:
    """Rewrite every mention of an ordinary name found across the project."""
    found = references.references(path, line, col, references.PROJECT, workspace.root)
    _reject_collision(workspace, found, old, new)
    for occurrence in found:
        _write(workspace.buffer(occurrence["module_path"]), occurrence, old, new)


def _write(buffer: Buffer, occurrence: dict, old: str, new: str) -> None:
    """Replace one mention, leaving alone anything that is not the name itself.

    A mention is located by line and column; an attribute's column is worked
    out from the text, so a spot that turns out to hold something else is not
    the reference it was taken for.
    """
    line, column = occurrence["line"], occurrence["column"]
    if buffer.lines[line - 1][column: column + len(old)] == old:
        buffer.replace((line, column), (line, column + len(old)), new)


def _reject_collision(workspace: Workspace, found: list[dict], old: str, new: str) -> None:
    """Refuse a rename that would leave two different things sharing one name."""
    defined = {(place["module_path"], place["line"], place["column"])
               for place in found if place["is_definition"]}
    for path in sorted({module_path for module_path, _, _ in defined}):
        buffer = workspace.buffer(path)
        tree = scopes.build(parse_tolerant(buffer.lines))
        for scope in tree.by_node.values():
            taken = _taken(scope, buffer, path, defined, old, new)
            if taken is not None:
                raise SithError(f"{new} is already defined at {path}:{taken}")


def _taken(scope: scopes.Scope, buffer: Buffer, path: str, defined: set, old: str,
           new: str) -> int | None:
    """The line where a scope already binds `new`, when it also binds the renamed name."""
    renamed = [
        binding
        for binding in scope.bindings
        if binding.name == old and _place(buffer, path, binding) in defined
    ]
    holders = [binding.lineno for binding in scope.bindings if binding.name == new]
    return holders[0] if renamed and holders else None


def _place(buffer: Buffer, path: str, binding: scopes.Binding) -> tuple[str, int, int]:
    """Where a binding writes its name, as a reference reports it."""
    column = definitions.name_column(buffer.lines, binding.node, binding.name)
    return (path, binding.lineno, column)
