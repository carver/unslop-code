"""The `rename` command: one symbol renamed everywhere the project spells it."""

from .edits import Edit, collect
from .errors import SithError
from .evaluator import Evaluator
from .modules import project_at
from .references import PROJECT, occurrences
from .relocation import module_target, rename_module
from .selections import check_identifier
from .source import name_at


def rename(path, line, column, new_name, options):
    """Rename what the cursor names, and its references, across the project.

    A cursor on a module name renames the file or package it stands for; any
    other name is rewritten wherever the project refers to that same symbol.
    """
    check_identifier(new_name)
    project = project_at(options)
    module = project.module(path)
    evaluator = Evaluator(project)
    target = module_target(project, evaluator, module, line, column)
    if target is not None:
        return rename_module(project, evaluator, target, new_name)
    return _rename_symbol(project, evaluator, module, line, column, new_name)


def _rename_symbol(project, evaluator, module, line, column, new_name):
    """Rewrite every occurrence of the symbol the cursor sits on."""
    name = name_at(module, line, column)[1]
    places = occurrences(evaluator, project, module, line, column, PROJECT)
    _check_free(places, name, new_name)
    return collect(project, [
        Edit(place.module.path, place.line, place.column,
             place.line, place.column + len(name), new_name)
        for place in places
    ])


def _check_free(places, name, new_name):
    """Refuse a rename the scope holding the definition has no room for."""
    for place in places:
        if not place.is_definition:
            continue
        scope = _declaring_scope(place.module.scope, place.line, place.column)
        if scope is not None and new_name in scope.declared():
            raise SithError(f"'{new_name}' is already defined where '{name}' is")


def _declaring_scope(scope, line, column):
    """The scope whose own bindings hold the one sitting at a position."""
    if any((binding.lineno, binding.column) == (line, column) for binding in scope.bindings):
        return scope
    found = (_declaring_scope(child, line, column) for child in scope.children)
    return next((holder for holder in found if holder is not None), None)
