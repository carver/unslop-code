"""Values backed by live Python objects.

Installed modules and builtins are introspected through the interpreter
itself; project files are never imported (see :mod:`sithlib.analysis`).
"""

from __future__ import annotations

import builtins
import functools
import importlib
import inspect
from typing import Dict, List, Optional

from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, STATEMENT, Symbol


class Value:
    """What a name refers to. ``members`` are the completions after a dot."""

    kind = STATEMENT
    label = ""

    def members(self) -> List[Symbol]:
        return []

    def attribute(self, name: str) -> Optional["Value"]:
        """The value of a single named attribute, or ``None`` if unknown."""
        return next((member.value for member in self.members() if member.name == name), None)


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


class RuntimeInstance(Value):
    """An instance of a live class, known only through its class."""

    kind = INSTANCE

    def __init__(self, cls):
        self.cls = cls
        self.label = cls.__name__

    def members(self):
        return [symbol_for(name, attribute_of(self.cls, name)) for name in dir(self.cls)]


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
