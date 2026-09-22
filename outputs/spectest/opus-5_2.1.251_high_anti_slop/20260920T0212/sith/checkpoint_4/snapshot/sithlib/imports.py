"""Resolving import statements to the modules and objects they bind."""

import ast
import os

from . import stubs
from .modules import Module
from .runtime import import_module, is_stdlib, stdlib_names
from .values import LiveValue, ModuleName, ModuleValue


class ImportResolver:
    """Follows imports, resolving project files before standard-library modules."""

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
        return self._exported(context, binding.node.module or "", binding.node.level)

    def completions(self, target, context):
        """Name -> entry for the names a half-typed import statement can bring in."""
        found = self._module_names(target, context)
        if target.members:
            found.update(self._exported(context, target.dotted, target.level))
        return found

    def _member(self, node, name, context):
        """What ``from module import name`` binds: a member, else a submodule."""
        dotted, level = node.module or "", node.level
        home = self._locate(context, dotted, level)
        if home is not None:
            entry = self._evaluator.members(self._value(home, dotted)).get(name)
            if entry is not None:
                return self._evaluator.entry_values(entry)
        return self._values_of(self._submodule(context, dotted, level, name), name)

    def _submodule(self, context, dotted, level, name):
        """The module a package holds under `name`, on disk or in the stdlib."""
        base = self._base(context, dotted, level)
        inside = self._project.module_at(os.path.join(base, name))
        if inside is not None or level:
            return inside
        return self._locate(context, _joined(dotted, name), 0)

    def _module_names(self, target, context):
        """The modules that can be named where the cursor sits in an import."""
        names = self._project.submodule_names(self._base(context, target.dotted, target.level))
        if not target.level:
            names = names + stdlib_names(target.dotted)
        return {name: ModuleName(_joined(target.dotted, name)) for name in names}

    def _exported(self, context, dotted, level):
        """Name -> entry for the public names of the module an import names."""
        home = self._locate(context, dotted, level)
        return exported(self._evaluator, self._value(home, dotted)) if home is not None else {}

    def _locate(self, context, dotted, level):
        return locate(self._project, context.module.path, dotted, level)

    def _base(self, context, dotted, level):
        return base_path(self._project, context.module.path, dotted, level)

    def _value(self, found, dotted):
        return _value_of(self._project, found, dotted)

    def _values_of(self, found, dotted):
        value = self._value(found, dotted)
        return [value] if value is not None else []


def locate(project, origin, dotted, level=0):
    """The module an import names: a project file, else a standard-library module.

    `origin` is the file holding the import, which relative imports climb from.
    A relative import never leaves the project; an absolute one that names no
    file of the project is looked up among the project's stubs, then in the
    standard library. Anything else - a missing module, an installed package
    without stubs - is unresolvable.
    """
    inside = project.module_at(base_path(project, origin, dotted, level))
    if inside is not None or level:
        return inside
    stub = stubs.stub_named(project, dotted)
    if stub is not None:
        return stub
    return import_module(dotted) if is_stdlib(dotted) else None


def base_path(project, origin, dotted, level):
    """The path an import name maps to, without an extension.

    A relative import climbs one directory per leading dot. Climbing past the
    project root gives the directory it escaped to, which lies outside the
    project and so holds nothing an import can reach.
    """
    if not level:
        return os.path.join(project.root, *dotted.split("."))
    directory = os.path.dirname(origin)
    for _ in range(level - 1):
        directory = os.path.dirname(directory)
    if not project.contains(directory):
        return directory
    return os.path.join(directory, *dotted.split(".")) if dotted else directory


def exported(evaluator, value):
    """Name -> entry for the names a module makes public.

    A module that declares ``__all__`` exports exactly those names; otherwise
    every name that does not start with an underscore is public.
    """
    members = evaluator.members(value)
    listed = _declared_all(value)
    if listed is None:
        return {name: entry for name, entry in members.items() if not name.startswith("_")}
    return {name: members[name] for name in listed if name in members}


def _declared_all(value):
    """The names a module's ``__all__`` lists, or ``None`` when it declares none."""
    if isinstance(value, LiveValue):
        return getattr(value.obj, "__all__", None)
    return _listed_all(value.module) if isinstance(value, ModuleValue) else None


def _listed_all(module):
    """The string elements of a parsed module's ``__all__`` assignment."""
    bound = module.scope.declared().get("__all__")
    listed = bound[-1].value if bound else None
    if not isinstance(listed, (ast.List, ast.Tuple)):
        return None
    return [item.value for item in listed.elts if isinstance(item, ast.Constant)]


def _joined(dotted, name):
    return f"{dotted}.{name}" if dotted else name


def _value_of(project, found, name):
    """Wrap a located module, which may have been parsed or imported."""
    if found is None:
        return None
    if isinstance(found, Module):
        return ModuleValue(found)
    return LiveValue(project, name.split(".")[-1], found)
