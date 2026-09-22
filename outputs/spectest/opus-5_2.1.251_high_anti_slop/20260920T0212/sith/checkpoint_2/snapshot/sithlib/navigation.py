"""Answering `what is this?` and `where does this come from?` at a cursor."""

import ast
import os

from .definitions import as_json
from .evaluator import Evaluator
from .modules import Context, Project
from .source import identifier_at
from .values import ClassValue, FunctionValue


def infer(path, line, column):
    """Definitions for what the name at the cursor evaluates to."""
    evaluator, node, context = _at_cursor(path, line, column)
    values = (evaluator.infer(node, context) if isinstance(node, ast.Attribute)
              else _values(evaluator, node, context))
    return as_json(value.definition() for value in values)


def goto(path, line, column):
    """Definitions for where the name at the cursor was bound."""
    evaluator, node, context = _at_cursor(path, line, column)
    entries = (evaluator.member_entries(evaluator.infer(node.value, context), node.attr)
               if isinstance(node, ast.Attribute)
               else _entries(evaluator, node, context))
    return as_json(evaluator.entry_definition(entry) for entry in entries)


def _at_cursor(path, line, column):
    """The evaluator, the node under the cursor, and where it sits."""
    project = Project(os.path.dirname(os.path.abspath(path)))
    module = project.module(path)
    node = identifier_at(module, line, column)
    text = module.lines[line - 1]
    return Evaluator(project), node, Context(module, line, len(text) - len(text.lstrip()))


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
