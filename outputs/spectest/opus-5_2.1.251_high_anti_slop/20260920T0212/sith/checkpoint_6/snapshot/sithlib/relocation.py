"""Renaming a module: the file it lives in, and every import that names it."""

import ast
import os
import re

from .edits import Edit, collect
from .errors import SithError
from .imports import locate, submodule
from .modules import Module
from .navigation import context_at
from .source import identifier_at, identifier_of
from .values import ModuleValue

_FROM = re.compile(r"from\s+\.*")


def module_target(project, evaluator, module, line, column):
    """The project module the cursor names, or ``None`` when it names something else.

    A module is named either inside an import statement, where the dotted name
    is no expression of its own, or by a name that evaluates to the module.
    """
    named = next((found for found, (found_line, start, length) in _module_names(project, module)
                  if found_line == line and start <= column <= start + length), None)
    if named is not None:
        return named
    return _module_value(evaluator, module, line, column)


def rename_module(project, evaluator, target, new_name):
    """Move a module's file or package directory, and rewrite the imports of it."""
    old_path, new_path = _paths(target, new_name)
    if os.path.exists(new_path):
        raise SithError(f"'{new_name}' already exists at {project.relative(new_path)}")
    old_name = target.name.split(".")[-1]
    edits = []
    for path in project.source_paths():
        source = project.module(path)
        edits.extend(_import_edits(project, source, target, new_name))
        edits.extend(_usage_edits(evaluator, source, target, old_name, new_name))
    renames = {project.relative(old_path): project.relative(new_path)}
    return collect(project, edits, renames)


def _paths(target, new_name):
    """Where the module lives now, and where the new name moves it to."""
    if os.path.basename(target.path).startswith("__init__"):
        directory = os.path.dirname(target.path)
        return directory, os.path.join(os.path.dirname(directory), new_name)
    suffix = os.path.splitext(target.path)[1]
    return target.path, os.path.join(os.path.dirname(target.path), new_name + suffix)


def _import_edits(project, module, target, new_name):
    """The import statements of one file, with the renamed component rewritten."""
    return [Edit(module.path, line, column, line, column + length, new_name)
            for found, (line, column, length) in _module_names(project, module)
            if found.path == target.path]


def _usage_edits(evaluator, module, target, old_name, new_name):
    """Every name outside an import statement that reads the renamed module."""
    for node in ast.walk(module.tree):
        if not isinstance(node, (ast.Name, ast.Attribute)):
            continue
        name, line, column = identifier_of(node, module.lines)
        if name != old_name:
            continue
        values = evaluator.infer(node, context_at(module, line))
        if any(isinstance(value, ModuleValue) and value.module.path == target.path
               for value in values):
            yield Edit(module.path, line, column, line, column + len(name), new_name)


def _module_names(project, module):
    """Every identifier naming a module inside the import statements of a file.

    Each one is paired with the module it resolves to and the ``(line, column,
    length)`` of the identifier, so that a cursor or a rename can find it.
    """
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield from _dotted(project, module, alias.name, 0,
                                   alias.lineno, alias.col_offset)
        elif isinstance(node, ast.ImportFrom):
            yield from _from_names(project, module, node)


def _from_names(project, module, node):
    """The modules a ``from`` import names: the dotted head, then its members."""
    dotted, level = node.module or "", node.level
    if node.module:
        opening = _FROM.match(module.lines[node.lineno - 1], node.col_offset)
        yield from _dotted(project, module, dotted, level, node.lineno, opening.end())
    for alias in node.names:
        found = submodule(project, module.path, dotted, level, alias.name)
        if found is not None:
            yield found, (alias.lineno, alias.col_offset, len(alias.name))


def _dotted(project, module, dotted, level, line, column):
    """Each component of a dotted module name, paired with the module it names."""
    parts = dotted.split(".")
    offset = 0
    for index, part in enumerate(parts):
        found = locate(project, module.path, ".".join(parts[:index + 1]), level)
        if isinstance(found, Module):
            yield found, (line, column + offset, len(part))
        offset += len(part) + 1


def _module_value(evaluator, module, line, column):
    """The module a name at the cursor evaluates to, when it evaluates to one."""
    values = evaluator.infer(identifier_at(module, line, column), context_at(module, line))
    return next((value.module for value in values if isinstance(value, ModuleValue)), None)
