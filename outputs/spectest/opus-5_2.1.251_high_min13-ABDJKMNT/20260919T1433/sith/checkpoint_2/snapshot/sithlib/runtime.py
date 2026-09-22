"""Values backed by live Python objects.

Installed modules and builtins are introspected through the interpreter
itself; project files are never imported (see :mod:`sithlib.analysis`).
"""

from __future__ import annotations

import builtins
import functools
import importlib
import inspect
from typing import Dict, Iterable, List, Optional

from .definitions import BUILTINS, Definition, qualified
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, STATEMENT, Symbol

NONE_NAME = "None"


class Value:
    """What a name refers to. ``members`` are the completions after a dot."""

    kind = STATEMENT
    label = ""

    def members(self) -> List[Symbol]:
        return []

    def attributes(self, name: str) -> List[Symbol]:
        """Every member of this value that carries ``name``."""
        return [member for member in self.members() if member.name == name]

    def attribute(self, name: str) -> Optional["Value"]:
        """The value of a single named attribute, or ``None`` if unknown."""
        return union([member.value for member in self.attributes(name)])

    def definitions(self) -> List[Definition]:
        """Where this value is defined, as reported by `infer`."""
        return []


class Union(Value):
    """Every value a name could hold, when a branch leaves it open."""

    def __init__(self, options: List[Value]):
        self.options = options
        self.kind = options[0].kind
        self.label = options[0].label

    def members(self):
        found: Dict[str, Symbol] = {}
        for option in self.options:
            for symbol in option.members():
                found.setdefault(symbol.name, symbol)
        return list(found.values())

    def attributes(self, name):
        """Each possibility answers for itself, so a union may hold several."""
        return [member for option in self.options for member in option.attributes(name)]

    def definitions(self):
        return [definition for option in self.options for definition in option.definitions()]


def union(values: Iterable[Optional[Value]]) -> Optional[Value]:
    """One value standing for every possibility in ``values``.

    Nested unions are flattened and unknown possibilities dropped, so a name
    that is only partly resolvable still reports what is known about it.
    """
    options: List[Value] = []
    for value in values:
        if value is None:
            continue
        options.extend(value.options if isinstance(value, Union) else [value])
    if not options:
        return None
    return options[0] if len(options) == 1 else Union(options)


class RuntimeValue(Value):
    """A live object: an imported module, a builtin, or an evaluated literal."""

    def __init__(self, obj):
        self.obj = obj
        self.kind = object_kind(obj)
        self.label = type(obj).__name__

    def members(self):
        names = dir(self.obj)
        if self.kind == MODULE:
            names = [name for name in names if not name.startswith("_")]
        return [symbol_for(name, attribute_of(self.obj, name)) for name in names]

    def attribute(self, name):
        member = attribute_of(self.obj, name)
        return RuntimeValue(member) if member is not None else None

    def definitions(self):
        described = type(self.obj) if self.kind == INSTANCE else self.obj
        return [runtime_definition(described, self.kind)]


class RuntimeInstance(Value):
    """An instance of a live class, known only through its class."""

    kind = INSTANCE

    def __init__(self, cls):
        self.cls = cls
        self.label = cls.__name__

    def members(self):
        return [symbol_for(name, attribute_of(self.cls, name)) for name in dir(self.cls)]

    def definitions(self):
        return [runtime_definition(self.cls, INSTANCE)]


def attribute_of(obj, name):
    """Look a name up without running descriptors such as properties."""
    return inspect.getattr_static(obj, name, None)


def object_kind(obj) -> str:
    """Classify a live object using the completion type vocabulary."""
    if inspect.ismodule(obj):
        return MODULE
    if inspect.isclass(obj):
        return CLASS
    if inspect.isroutine(obj) or isinstance(obj, (staticmethod, classmethod)):
        return FUNCTION
    return INSTANCE


def symbol_for(name: str, obj) -> Symbol:
    """Describe a live object as a completion symbol."""
    return Symbol(name=name, kind=object_kind(obj), label=type(obj).__name__, value=RuntimeValue(obj))


NONE = RuntimeValue(None)
"""The value of a bare ``None`` and of a function that returns nothing."""


def is_none(value: Optional[Value]) -> bool:
    """Whether a value is the ``None`` singleton."""
    return isinstance(value, RuntimeValue) and value.obj is None


def without_none(value: Optional[Value]) -> Optional[Value]:
    """``value`` with the ``None`` possibility removed."""
    options = value.options if isinstance(value, Union) else [value]
    return union([option for option in options if not is_none(option)])


# --------------------------------------------------------------------------
# Definitions of live objects
# --------------------------------------------------------------------------


def runtime_definition(obj, kind: str) -> Definition:
    """Describe a live object as a definition record.

    Objects written in C - every builtin type among them - have no source, so
    they are reported with an empty path at line and column zero.
    """
    name, qualname = runtime_names(obj)
    module = "" if kind == MODULE else getattr(obj, "__module__", BUILTINS) or BUILTINS
    line, path = source_position(obj)
    return Definition(
        name=name,
        type=kind,
        full_name=qualified(module, qualname),
        module_path=path,
        line=line,
        column=0,
        description=runtime_description(obj, kind, name),
        docstring=inspect.getdoc(obj) or "",
    )


def runtime_names(obj):
    """The short and qualified names of a live object, `None` spelling its own."""
    if obj is type(None):
        return NONE_NAME, NONE_NAME
    name = getattr(obj, "__name__", type(obj).__name__)
    return name, getattr(obj, "__qualname__", name)


def source_position(obj):
    """The line and file an object was written at, when it has one."""
    try:
        path = inspect.getsourcefile(obj)
        if path is None or inspect.ismodule(obj):
            return 0, path or ""
        return inspect.getsourcelines(obj)[1], path
    except (OSError, TypeError):
        return 0, ""


def runtime_description(obj, kind: str, name: str) -> str:
    """The short description of a live object."""
    if kind == FUNCTION:
        return f"def {name}({parameters(obj)})"
    return DESCRIPTIONS[kind].format(name=name)


DESCRIPTIONS = {
    MODULE: "module {name}",
    CLASS: "class {name}",
    INSTANCE: "instance of {name}",
    STATEMENT: "{name}",
}


def parameters(obj) -> str:
    """The parameter list of a live callable, elided when it cannot be read."""
    try:
        return str(inspect.signature(obj))[1:-1]
    except (TypeError, ValueError):
        return "..."


@functools.cache
def builtin_symbols() -> List[Symbol]:
    """Every name provided by the ``builtins`` module."""
    return [symbol_for(name, getattr(builtins, name)) for name in dir(builtins)]


@functools.cache
def builtin_index() -> Dict[str, Symbol]:
    """Builtin symbols keyed by name."""
    return {symbol.name: symbol for symbol in builtin_symbols()}


@functools.cache
def import_module(name: str):
    """Import an installed module, or return ``None`` when it is unavailable.

    Importing runs module level code, so any failure is treated as "unknown".
    """
    try:
        return importlib.import_module(name)
    except Exception:
        return None
