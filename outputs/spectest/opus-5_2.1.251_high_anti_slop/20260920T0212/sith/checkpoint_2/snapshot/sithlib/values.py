"""What an expression can evaluate to, and the definition each possibility prints."""

import ast
import inspect
from dataclasses import dataclass

from . import symbols
from .bindings import identifier_column, signature
from .definitions import Definition


@dataclass(frozen=True)
class ClassValue:
    """A class defined in a parsed module, or an instance of that class."""

    module: object
    node: ast.ClassDef
    instance: bool = False

    def as_instance(self):
        return ClassValue(self.module, self.node, True)

    def definition(self):
        name = self.node.name
        if self.instance:
            return self._record(symbols.INSTANCE, f"instance of {name}")
        return self._record(symbols.CLASS, f"class {name}")

    def _record(self, kind, description):
        return _defined_in(self.module, self.node, kind, description)


@dataclass(frozen=True)
class FunctionValue:
    """A function or method defined in a parsed module."""

    module: object
    node: ast.FunctionDef

    def definition(self):
        return _defined_in(self.module, self.node, symbols.FUNCTION, signature(self.node))


@dataclass(frozen=True)
class ModuleValue:
    """A module of the project that was parsed rather than imported."""

    module: object

    def definition(self):
        name = self.module.name
        return Definition(
            name=name.rsplit(".", 1)[-1],
            type=symbols.MODULE,
            full_name=name,
            module_path=self.module.relative_path,
            line=0,
            column=0,
            description=f"module {name}",
            docstring=ast.get_docstring(self.module.tree) or "",
        )


@dataclass(frozen=True)
class BuiltinValue:
    """An instance of a builtin type, such as the value of a literal."""

    type_name: str

    def definition(self):
        return Definition(
            name=self.type_name,
            type=symbols.INSTANCE,
            full_name=f"builtins.{self.type_name}",
            module_path="",
            line=0,
            column=0,
            description=f"instance of {self.type_name}",
            docstring="",
        )


@dataclass(frozen=True)
class LiveValue:
    """An object reached by importing it, rather than by reading its source."""

    project: object
    name: str
    obj: object
    instance: bool = False

    def definition(self):
        kind, description = _classify(self.name, self.obj, self.instance)
        path, line = _location(self.obj, self.project)
        docstring = "" if kind == symbols.INSTANCE else inspect.getdoc(self.obj)
        return Definition(
            name=self.name,
            type=kind,
            full_name=_live_full_name(self.obj),
            module_path=path,
            line=line,
            column=0,
            description=description,
            docstring=docstring or "",
        )


NONE = BuiltinValue("None")


def instantiate(value):
    """The value a call to `value` produces, or ``None`` when it is not a class."""
    if isinstance(value, ClassValue) and not value.instance:
        return value.as_instance()
    if not isinstance(value, LiveValue) or not inspect.isclass(value.obj):
        return None
    if value.obj.__module__ == "builtins":
        return BuiltinValue(value.obj.__name__)
    return LiveValue(value.project, value.name, value.obj, instance=True)


def _defined_in(module, node, kind, description):
    """The definition of a class or function node inside a parsed module."""
    return Definition(
        name=node.name,
        type=kind,
        full_name=module.qualified_name(node),
        module_path=module.relative_path,
        line=node.lineno,
        column=identifier_column(module.lines, node.lineno, node.name, node.col_offset),
        description=description,
        docstring=ast.get_docstring(node) or "",
    )


def _classify(name, obj, instance=False):
    """The definition type and description of a live object."""
    if instance:
        return symbols.INSTANCE, f"instance of {obj.__name__}"
    if inspect.ismodule(obj):
        return symbols.MODULE, f"module {obj.__name__}"
    if inspect.isclass(obj):
        return symbols.CLASS, f"class {obj.__name__}"
    if inspect.isroutine(obj):
        return symbols.FUNCTION, f"def {name}{_live_signature(obj)}"
    return symbols.INSTANCE, f"instance of {type(obj).__name__}"


def _live_signature(obj):
    """The parameter list of a live callable; C functions do not expose one."""
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "(...)"


def _live_full_name(obj):
    """The dotted name a live object reports for itself."""
    if inspect.ismodule(obj):
        return obj.__name__
    home = getattr(obj, "__module__", None)
    qualified = getattr(obj, "__qualname__", None)
    if home and qualified:
        return f"{home}.{qualified}"
    return f"builtins.{type(obj).__name__}"


def _location(obj, project):
    """Where a live object was written, or nothing for objects without source."""
    try:
        path = inspect.getsourcefile(obj)
        _, start = inspect.getsourcelines(obj)
    except (TypeError, OSError):
        return "", 0
    return (project.relative(path), start) if path else ("", 0)
