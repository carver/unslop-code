"""Answering `what is this?` and `where does this come from?` at a cursor."""

import ast

from .bindings import IMPORT, Reference
from .definitions import as_json
from .evaluator import Evaluator
from .modules import Context, project_for
from .source import identifier_at
from .values import ClassValue, FunctionValue, ModuleValue

_PARSED = (ClassValue, FunctionValue, ModuleValue)


def infer(path, line, column, root=None, dynamic=True):
    """Definitions for what the name at the cursor evaluates to."""
    evaluator, node, context = _at_cursor(path, line, column, root, dynamic)
    values = (evaluator.infer(node, context) if isinstance(node, ast.Attribute)
              else _values(evaluator, node, context))
    return as_json(value.definition() for value in values)


def goto(path, line, column, follow_imports=False, root=None):
    """Definitions for where the name at the cursor was bound."""
    evaluator, node, context = _at_cursor(path, line, column, root)
    entries = entries_at(evaluator, node, context)
    return as_json(_definitions(evaluator, entries, follow_imports))


def entries_at(evaluator, node, context):
    """The entries a node resolves to: the bindings behind it, or its own value."""
    if isinstance(node, ast.Attribute):
        return evaluator.member_entries(evaluator.infer(node.value, context), node.attr)
    return _entries(evaluator, node, context)


def context_at(module, line):
    """The context a node on a source line is resolved in."""
    text = module.lines[line - 1]
    return Context(module, line, len(text) - len(text.lstrip()))


def _at_cursor(path, line, column, root, dynamic=True):
    """The evaluator, the node under the cursor, and where it sits."""
    project = project_for(path, root)
    module = project.module(path)
    node = identifier_at(module, line, column)
    return Evaluator(project, dynamic), node, context_at(module, line)


def _values(evaluator, node, context):
    """What the node under the cursor evaluates to."""
    name = _bound_name(node)
    if name is None:
        return _standalone(evaluator, node, context)
    return evaluator.infer_name(name, context)


def _entries(evaluator, node, context):
    """The places that bind the node under the cursor."""
    name = _bound_name(node)
    if name is None:
        return _standalone(evaluator, node, context)
    return evaluator.lookup(name, context)


def _definitions(evaluator, entries, follow_imports):
    """The records `goto` prints for what the cursor resolved to.

    Imports normally report themselves; `follow_imports` reports the definition
    they lead to instead, keeping the import statement as the fallback for a
    chain that leaves the project or ends nowhere.
    """
    found = []
    for entry in entries:
        followed = imported_source(evaluator, entry) if follow_imports else []
        found.extend(followed or [evaluator.entry_definition(entry)])
    return found


def imported_source(evaluator, entry):
    """Where an import statement's name is defined, when project source has it."""
    if not (isinstance(entry, Reference) and entry.binding.kind == IMPORT):
        return []
    return [value.definition() for value in evaluator.entry_values(entry)
            if isinstance(value, _PARSED)]


def _bound_name(node):
    """The name a node refers to, or ``None`` when the node stands on its own."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.alias):
        return node.asname or node.name.split(".")[0]
    return None


def _standalone(evaluator, node, context):
    """Values for a node that refers to no name: a definition or a literal."""
    if isinstance(node, ast.Constant):
        return evaluator.infer(node, context)
    if isinstance(node, ast.ClassDef):
        return [ClassValue(context.module, node)]
    return [FunctionValue(context.module, node)]
