"""The `references` command: every place one symbol is used or defined.

Occurrences are matched by identity, not by spelling: a candidate counts only
when it resolves to the definition the cursor resolves to, so that unrelated
names of other scopes stay out of the answer.
"""

import ast

from .evaluator import Evaluator
from .modules import project_for
from .navigation import context_at, entries_at, imported_source
from .source import identifier_at, identifier_of

FILE = "file"
PROJECT = "project"

_DECLARING = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.arg, ast.alias)


def references(path, line, column, scope=FILE, root=None):
    """Where the name at the cursor is referenced, in its file or the project."""
    project = project_for(path, root)
    module = project.module(path)
    evaluator = Evaluator(project)
    node = identifier_at(module, line, column)
    name, found_line, _ = identifier_of(node, module.lines)
    wanted = _identity(evaluator, module, node, found_line)

    found = {}
    for searched in _searched(project, module, scope):
        found.update(_matches(evaluator, searched, name, wanted))
    return [_occurrence(place, defining) for place, defining in sorted(found.items())]


def _occurrence(place, defining):
    """One occurrence as the JSON object the command prints."""
    module_path, line, column = place
    return {
        "module_path": module_path,
        "line": line,
        "column": column,
        "is_definition": defining,
    }


def _searched(project, module, scope):
    """The modules a search covers: the cursor's file, or all project sources."""
    if scope == FILE:
        return [module]
    return [project.module(path) for path in project.source_paths()]


def _matches(evaluator, module, name, wanted):
    """Place -> whether it defines, for the occurrences of one symbol in a module."""
    return {
        (module.relative_path, line, column): _is_definition(node)
        for node, line, column in _occurrences(module, name)
        if _identity(evaluator, module, node, line) & wanted
    }


def _occurrences(module, name):
    """Every node of a module spelling `name`, with where its identifier sits."""
    for node in ast.walk(module.tree):
        found = identifier_of(node, module.lines)
        if found is not None and found[0] == name:
            yield node, found[1], found[2]


def _identity(evaluator, module, node, line):
    """The definitions a node resolves to, which is what identifies its symbol.

    An import both defines a name of its own and refers to the definition it
    leads to, so both places take part in its identity.
    """
    entries = entries_at(evaluator, node, context_at(module, line))
    definitions = [evaluator.entry_definition(entry) for entry in entries]
    definitions += [reached for entry in entries
                    for reached in imported_source(evaluator, entry)]
    return frozenset(
        (definition.module_path, definition.line, definition.column)
        for definition in definitions
    )


def _is_definition(node):
    """Whether an occurrence is the one that introduces the name."""
    if isinstance(node, _DECLARING):
        return True
    return isinstance(getattr(node, "ctx", None), ast.Store)
