"""The `inline` command: a variable replaced by the expression it holds."""

from __future__ import annotations

import ast

from . import precedence, project, references, spans
from .definitions import Definition
from .edits import Buffer, Workspace
from .navigate import definitions_at
from .options import DEFAULT, Options
from .refactor import at_cursor
from .source import SithError

NO_REFERENCES = "name has no references to inline"
NOT_A_VARIABLE = "cannot inline a function/class definition"


def inline(path: str, line: int, col: int, root: str | None = None, diff: bool = False,
           options: Options = DEFAULT) -> dict | str:
    """Replace every use of the variable at the cursor with its value."""
    root = project.root_of(path, root)
    analysis, reference = at_cursor(path, line, col, root, options)
    workspace = Workspace(root)
    definition = _definition(analysis, reference)
    buffer = workspace.buffer(definition.module_path)
    assignment = _assignment(buffer, definition, reference.name)
    uses = [
        place
        for place in references.references(path, line, col, references.PROJECT, root, options)
        if not place["is_definition"]
    ]
    if not uses:
        raise SithError(NO_REFERENCES)
    _substitute(workspace, uses, buffer.original, assignment.value)
    buffer.replace_lines(assignment.lineno, assignment.end_lineno, [])
    return workspace.answer(diff)


def _definition(analysis, reference) -> Definition:
    """Where the name at the cursor was defined; there has to be exactly one place."""
    found = definitions_at(analysis, reference)
    if len(found) != 1:
        raise SithError(f"{reference.name} is not defined in one place")
    return found[0]


def _assignment(buffer: Buffer, definition: Definition, name: str) -> ast.Assign:
    """The `name = <expr>` statement the definition stands for, or a refusal."""
    tree = spans.parse(buffer.original, buffer.path)
    statement = spans.statement_containing(tree, (definition.line, definition.column))
    if isinstance(statement, spans.DEFINITIONS) and statement.name == name:
        raise SithError(NOT_A_VARIABLE)
    if statement is None or not _is_simple(statement, name):
        raise SithError(f"cannot inline {name}: it is not a simple assignment")
    return statement


def _is_simple(statement: ast.stmt, name: str) -> bool:
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == name
    )


def _substitute(workspace: Workspace, uses: list[dict], text: str, value: ast.expr) -> None:
    """Write the value where each use of the name stands, bracketed as needed."""
    source = ast.get_source_segment(text, value)
    for path, places in _by_file(uses).items():
        buffer = workspace.buffer(path)
        tree = spans.parse(buffer.original, path)
        parents = spans.parents(tree)
        for place in places:
            node = spans.name_at(tree, place)
            if node is not None:
                parent, field = parents[id(node)]
                buffer.replace(*spans.span(node),
                               precedence.bracket(source, value, parent, field))


def _by_file(uses: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """The positions of the uses, grouped by the file they were found in."""
    found: dict[str, list[tuple[int, int]]] = {}
    for use in uses:
        found.setdefault(use["module_path"], []).append((use["line"], use["column"]))
    return found
