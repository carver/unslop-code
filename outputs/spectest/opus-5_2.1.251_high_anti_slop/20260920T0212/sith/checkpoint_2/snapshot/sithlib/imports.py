"""Resolving import statements to the modules and objects they bind."""

import ast
import os

from .modules import Module
from .runtime import import_module
from .values import LiveValue, ModuleValue


class ImportResolver:
    """Follows imports, preferring files of the project over installed packages."""

    def __init__(self, evaluator, project):
        self._evaluator = evaluator
        self._project = project

    def values(self, binding, context):
        """What one name of an import statement binds to."""
        node, alias = binding.node, binding.value
        if isinstance(node, ast.Import):
            dotted = alias.name if alias.asname else alias.name.split(".")[0]
            return self._values_of(self._locate(context, dotted, 0), dotted)
        return self._member(node, alias.name, context)

    def star_members(self, binding, context):
        """The public names a ``from module import *`` statement brings in."""
        node = binding.node
        home = self._locate(context, node.module or "", node.level)
        members = self._evaluator.members(_value_of(self._project, home, node.module or ""))
        return {name: entry for name, entry in members.items() if not name.startswith("_")}

    def _member(self, node, name, context):
        """What ``from module import name`` binds: a member, else a submodule."""
        home = self._locate(context, node.module or "", node.level)
        if home is not None:
            entry = self._evaluator.members(_value_of(self._project, home, name)).get(name)
            if entry is not None:
                return self._evaluator.entry_values(entry)
        return self._values_of(self._submodule(home, name, context), name)

    def _submodule(self, home, name, context):
        """The module ``name`` names inside an already located package."""
        if isinstance(home, Module):
            return self._project.module_at(os.path.join(os.path.dirname(home.path), name))
        if home is None:
            return None
        return self._locate(context, f"{home.__name__}.{name}", 0)

    def _locate(self, context, dotted, level):
        return locate(self._project, context.module.path, dotted, level)

    def _values_of(self, found, dotted):
        value = _value_of(self._project, found, dotted)
        return [value] if value is not None else []


def locate(project, origin, dotted, level=0):
    """The module an import names: a parsed project file, else a live import.

    `origin` is the file holding the import, which relative imports climb from.
    """
    if level:
        return _relative(project, origin, dotted, level)
    inside = project.module_named(dotted)
    return inside if inside is not None else import_module(dotted, project.root)


def _relative(project, origin, dotted, level):
    """The module ``from ..pkg import x`` refers to, always a file on disk."""
    directory = os.path.dirname(origin)
    for _ in range(level - 1):
        directory = os.path.dirname(directory)
    return project.module_at(os.path.join(directory, *dotted.split(".")) if dotted else directory)


def _value_of(project, found, name):
    """Wrap a located module, which may have been parsed or imported."""
    if found is None:
        return None
    if isinstance(found, Module):
        return ModuleValue(found)
    return LiveValue(project, name.split(".")[-1], found)
