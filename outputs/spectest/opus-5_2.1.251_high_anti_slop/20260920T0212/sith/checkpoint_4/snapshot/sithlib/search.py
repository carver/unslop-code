"""The `search` and `names` commands: the definitions a project declares."""

from .bindings import ASSIGN, CLASS, FUNCTION, Reference, TARGET
from .definitions import as_record, without_docstring
from .evaluator import Evaluator
from .modules import project_at, project_for
from .scopes import CLASS_SCOPE, STAR

_SEARCHABLE = (CLASS, FUNCTION, ASSIGN, TARGET)


def search(query, root=None):
    """The definitions of the project whose name matches `query`.

    Exact matches come first, then the names starting with the query, then
    the ones merely holding it; each group runs in project order.
    """
    project = project_at(root)
    evaluator = Evaluator(project)
    found = [
        ((rank, module.relative_path, binding.lineno),
         evaluator.entry_definition(Reference(module, binding)))
        for module in (project.module(path) for path in project.source_paths())
        for rank, binding in _matching(module, query)
    ]
    return [without_docstring(definition)
            for _, definition in sorted(found, key=lambda item: item[0])]


def names(path, all_scopes=False, root=None):
    """The names a file defines: its module-level ones, or those of every scope."""
    project = project_for(path, root)
    module = project.module(path)
    evaluator = Evaluator(project)
    scopes = _nested(module.scope) if all_scopes else [module.scope]
    declared = sorted(
        (binding for scope in scopes for binding in scope.bindings if binding.name != STAR),
        key=lambda binding: (binding.lineno, binding.column),
    )
    return [
        as_record(evaluator.entry_definition(Reference(module, binding)), is_definition=True)
        for binding in declared
    ]


def _matching(module, query):
    """The (rank, binding) pairs of a module for the names a query matches."""
    ranked = ((_rank(binding.name, query), binding) for binding in _declarations(module.scope))
    return [(rank, binding) for rank, binding in ranked if rank is not None]


def _declarations(scope):
    """The names a module or class body declares, skipping function bodies."""
    for binding in scope.bindings:
        if binding.kind in _SEARCHABLE:
            yield binding
    for child in scope.children:
        if child.kind == CLASS_SCOPE:
            yield from _declarations(child)


def _nested(scope):
    """A scope and every scope inside it."""
    return [scope] + [found for child in scope.children for found in _nested(child)]


def _rank(name, query):
    """0 for an exact match, 1 for a prefix, 2 for a substring, ``None`` for none."""
    lowered, wanted = name.lower(), query.lower()
    if lowered == wanted:
        return 0
    if lowered.startswith(wanted):
        return 1
    return 2 if wanted in lowered else None
