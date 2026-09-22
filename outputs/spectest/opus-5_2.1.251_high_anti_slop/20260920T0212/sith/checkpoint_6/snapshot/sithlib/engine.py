"""Turning a cursor position in a file into ranked completions."""

import keyword

from . import symbols
from .evaluator import Evaluator
from .matching import matches
from .modules import Context, project_at
from .source import locate


def complete(path, line, column, fuzzy, options):
    """The completion records for the cursor at 1-based `line`, 0-based `column`."""
    settings = options.settings
    project = project_at(options)
    module = project.module(path)
    cursor = locate(module.lines, line, column)
    evaluator = Evaluator(project, settings.dynamic_params, options.namespace)
    context = Context(module, cursor.line, cursor.indent)

    entries, words = _candidates(evaluator, cursor, context)
    offered = [(name, symbols.KEYWORD) for name in words] + [(name, None) for name in entries]
    matched = sorted(
        [(name, kind) for name, kind in offered
         if matches(name, cursor.prefix, fuzzy, settings.case_insensitive)],
        key=lambda candidate: symbols.sort_key(*candidate),
    )
    return [
        _completion(evaluator, entries, name, kind, len(cursor.prefix), settings)
        for name, kind in matched
    ]


def _candidates(evaluator, cursor, context):
    """The entries a cursor can complete, and the keywords it may also accept."""
    if cursor.imports is not None:
        return evaluator.imports.completions(cursor.imports, context), []
    if cursor.receiver is None:
        return evaluator.visible_entries(context), keyword.kwlist
    return _members(evaluator, evaluator.infer(cursor.receiver, context)), []


def _members(evaluator, values):
    """The attributes of every type a receiver may hold, merged into one set."""
    found = {}
    for value in values:
        found.update(evaluator.members(value))
    return found


def _completion(evaluator, entries, name, kind, prefix_length, settings):
    if kind == symbols.KEYWORD:
        return symbols.as_completion(name, kind, name, prefix_length)
    kind, description = evaluator.entry_display(entries[name])
    return symbols.as_completion(name, kind, description, prefix_length, settings.add_bracket)
