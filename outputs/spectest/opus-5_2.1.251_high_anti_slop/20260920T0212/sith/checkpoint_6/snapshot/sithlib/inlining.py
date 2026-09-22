"""The `inline` command: a variable replaced everywhere by the value it holds."""

import ast

from .bindings import ASSIGN, CLASS, FUNCTION, Reference
from .edits import Edit, collect
from .errors import SithError
from .evaluator import Evaluator
from .modules import project_at
from .navigation import context_at, entries_at
from .precedence import parenthesized, slots
from .references import FILE, occurrences
from .source import name_at, span_text

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def inline(path, line, column, options):
    """Replace every reference to the variable at the cursor with its value.

    References are searched in the cursor's own file: a value only makes sense
    where the names it is written with are in scope.
    """
    project = project_at(options)
    module = project.module(path)
    evaluator = Evaluator(project)
    binding = _inlined(evaluator, module, line, column)
    places = occurrences(evaluator, project, module, line, column, FILE)
    uses = [place for place in places if not place.is_definition]
    assignments = [place for place in places if place.is_definition]
    if not uses:
        raise SithError("name has no references to inline")
    if len(assignments) > 1:
        raise SithError(f"'{binding.name}' is assigned more than once")
    return collect(project, _edits(module, binding, uses))


def _inlined(evaluator, module, line, column):
    """The binding the cursor names, once it is one a value can replace."""
    node, name, found_line = name_at(module, line, column)
    entries = entries_at(evaluator, node, context_at(module, found_line))
    bindings = [entry.binding for entry in entries if isinstance(entry, Reference)]
    kinds = {binding.kind for binding in bindings}
    if isinstance(node, _DEFINITIONS) or kinds & {FUNCTION, CLASS}:
        raise SithError("cannot inline a function/class definition")
    found = next((binding for binding in bindings if _is_simple(binding)), None)
    if found is None:
        raise SithError(f"'{name}' is not bound by a simple assignment")
    return found


def _is_simple(binding):
    """Whether a binding is a plain ``name = value`` statement."""
    return (binding.kind == ASSIGN and isinstance(binding.node, ast.Assign)
            and len(binding.node.targets) == 1)


def _edits(module, binding, uses):
    """Every reference rewritten as the value, and the assignment line dropped."""
    value = binding.value
    text = span_text(module.lines, value.lineno, value.col_offset,
                     value.end_lineno, value.end_col_offset)
    placed = slots(module.tree)
    statement = binding.node
    return [
        Edit(module.path, node.lineno, node.col_offset,
             node.lineno, node.col_offset + len(binding.name),
             parenthesized(text, value, placed[id(node)]))
        for node in _referencing(module.tree, uses)
    ] + [Edit(module.path, statement.lineno, 0, statement.end_lineno + 1, 0, "")]


def _referencing(tree, uses):
    """The Name nodes the referring occurrences sit on."""
    wanted = {(place.line, place.column) for place in uses}
    found = {(node.lineno, node.col_offset): node for node in ast.walk(tree)
             if isinstance(node, ast.Name) and (node.lineno, node.col_offset) in wanted}
    if len(found) != len(wanted):
        raise SithError("the name is used where its value cannot stand in")
    return found.values()
