"""The value model.

Every name a completion can offer is backed by a :class:`Value`.  A value
knows how it should be reported (``kind`` and ``description``) and which
attributes it exposes, which is all that completion needs.  Values come either
from real Python objects (installed packages, builtins) or from source that was
parsed but never executed.
"""

from __future__ import annotations

import functools
import inspect
import types
from dataclasses import dataclass
from typing import Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .scopes import Definition, Scope


@dataclass(frozen=True)
class Symbol:
    """A name together with the value it is bound to."""

    name: str
    value: Value


class Value:
    """Base class: something a name can refer to."""

    kind = "statement"
    description = "statement"

    def attributes(self) -> list[Symbol]:
        return []

    def attribute(self, name: str) -> Value | None:
        return next((symbol.value for symbol in self.attributes() if symbol.name == name), None)


class Unknown(Value):
    """A binding whose value could not be inferred."""


UNKNOWN = Unknown()


@dataclass(frozen=True)
class Keyword(Value):
    """A reserved word of the language."""

    word: str
    kind = "keyword"

    @property
    def description(self) -> str:
        return self.word


@dataclass(frozen=True)
class Param(Value):
    """A function parameter, optionally typed by its annotation."""

    annotated: Value = UNKNOWN
    kind = "param"
    description = "param"

    def attributes(self) -> list[Symbol]:
        return self.annotated.attributes()


@dataclass(frozen=True)
class RuntimeObject(Value):
    """A live Python object reached through an actual import.

    ``public_only`` is set for modules, whose spec'd attribute set is limited to
    names that do not start with an underscore.
    """

    obj: object
    kind: str
    description: str
    public_only: bool = False

    def attributes(self) -> list[Symbol]:
        names = dir(self.obj)
        if self.public_only:
            names = [name for name in names if not name.startswith("_")]
        return [Symbol(name, runtime_value(getattr(self.obj, name, None), name)) for name in names]


def runtime_value(obj: object, label: str) -> Value:
    """Classify a live object into the value that describes it."""
    if inspect.ismodule(obj):
        return RuntimeObject(obj, "module", f"module {label}", public_only=True)
    if inspect.isclass(obj):
        return RuntimeObject(obj, "class", f"class {obj.__name__}")
    if callable(obj):
        return RuntimeObject(obj, "function", f"def {label}(...)")
    return runtime_instance(type(obj))


def runtime_instance(cls: type) -> Value:
    """An instance of a live class; its attributes are the class' attributes."""
    return RuntimeObject(cls, "instance", f"instance of {cls.__name__}")


@dataclass(frozen=True)
class SourceModule(Value):
    """A module of the project that was parsed rather than imported."""

    scope: Scope
    name: str
    kind = "module"

    @property
    def description(self) -> str:
        return f"module {self.name}"

    def attributes(self) -> list[Symbol]:
        return _symbols(definition for definition in self.scope.definitions
                        if not definition.name.startswith("_"))


@dataclass(frozen=True)
class SourceFunction(Value):
    """A ``def`` or ``lambda`` in parsed source."""

    name: str
    kind = "function"

    @property
    def description(self) -> str:
        return f"def {self.name}(...)"

    def attributes(self) -> list[Symbol]:
        return runtime_instance(types.FunctionType).attributes()


def _non_recursive(
        method: Callable[[SourceClass], list[Symbol]]) -> Callable[[SourceClass], list[Symbol]]:
    """Stop a class hierarchy that refers back to itself from expanding forever.

    Source being edited can describe a cycle that real Python would reject;
    a class already on the stack simply contributes nothing the second time.
    """
    expanding: set[int] = set()

    @functools.wraps(method)
    def guarded(self: SourceClass) -> list[Symbol]:
        if id(self) in expanding:
            return []
        expanding.add(id(self))
        try:
            return method(self)
        finally:
            expanding.discard(id(self))

    return guarded


@dataclass(frozen=True)
class SourceClass(Value):
    """A ``class`` in parsed source.

    ``bases`` is deferred because a base name is resolved through the scope the
    class is written in, which is still being populated at build time.
    """

    name: str
    scope: Scope
    bases: Callable[[], list[Value]]
    self_attributes: list[Definition]
    kind = "class"

    @property
    def description(self) -> str:
        return f"class {self.name}"

    @_non_recursive
    def attributes(self) -> list[Symbol]:
        inherited = [symbol for base in self.bases() for symbol in base.attributes()]
        return _merge(_symbols(self.scope.definitions), inherited)

    @_non_recursive
    def instance_attributes(self) -> list[Symbol]:
        """Attributes assigned on ``self``, including those of the bases."""
        inherited = [
            symbol
            for base in self.bases()
            if isinstance(base, SourceClass)
            for symbol in base.instance_attributes()
        ]
        return _merge(_symbols(self.self_attributes), inherited)


@dataclass(frozen=True)
class SourceInstance(Value):
    """An instance of a :class:`SourceClass`."""

    cls: SourceClass
    kind = "instance"

    @property
    def description(self) -> str:
        return f"instance of {self.cls.name}"

    def attributes(self) -> list[Symbol]:
        return _merge(self.cls.instance_attributes(), self.cls.attributes())


def _symbols(definitions: Iterable[Definition]) -> list[Symbol]:
    return [Symbol(definition.name, definition.value()) for definition in definitions]


def _merge(*groups: Iterable[Symbol]) -> list[Symbol]:
    """Concatenate symbol groups, keeping the first binding of each name."""
    merged: dict[str, Symbol] = {}
    for group in groups:
        for symbol in group:
            merged.setdefault(symbol.name, symbol)
    return list(merged.values())
