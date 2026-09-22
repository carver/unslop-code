"""The value model.

Every name a completion can offer is backed by a :class:`Value`.  A value knows
how it should be reported (``kind``, ``description`` and the definitions it
points at) and which attributes it exposes, which is all that completion,
inference and navigation need.  Values come either from real Python objects
(installed packages, builtins) or from source that was parsed but never
executed.
"""

from __future__ import annotations

import functools
import inspect
import types
from dataclasses import dataclass, replace
from typing import Callable, Iterable, TYPE_CHECKING

from .definitions import Definition

if TYPE_CHECKING:
    from .scopes import Binding, Scope


class Lazy:
    """A value produced on demand, at most once.

    Producing a value may import a module or walk another scope, and can come
    back round to the value being produced; a value that is already being
    resolved reports as unknown rather than being chased in circles.
    """

    def __init__(self, resolver: Callable[[], Value]) -> None:
        self._resolver = resolver
        self._value: Value | None = None
        self._resolving = False

    def value(self) -> Value:
        if self._value is None:
            if self._resolving:
                return UNKNOWN
            self._resolving = True
            try:
                self._value = self._resolver()
            finally:
                self._resolving = False
        return self._value


@dataclass(frozen=True)
class Symbol:
    """A name, the value it is bound to and, when known, the binding that wrote it.

    A symbol that came from parsed source keeps its binding, because where the
    name was written and where the import it came through leads are two
    different answers that ``goto`` picks between.
    """

    name: str
    value: Value
    binding: Binding | None = None

    def site(self) -> list[Definition]:
        """Where the name was written down; for an import, the import statement."""
        return [self.binding.definition()] if self.binding else self.value.definitions()

    def origin(self) -> list[Definition]:
        """Where the name was written down, following the imports it came through."""
        return self.binding.followed() if self.binding else self.value.definitions()


class Value:
    """Base class: something a name can refer to."""

    kind = "statement"
    description = "statement"

    def attributes(self) -> list[Symbol]:
        return []

    def symbol(self, name: str) -> Symbol | None:
        """One named attribute, carrying where it was written when that is known."""
        return next((symbol for symbol in self.attributes() if symbol.name == name), None)

    def attribute(self, name: str) -> Value | None:
        found = self.symbol(name)
        return found.value if found is not None else None

    def definitions(self) -> list[Definition]:
        """What ``infer`` reports; empty when there is nothing to point at."""
        return []


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

    def definitions(self) -> list[Definition]:
        return self.annotated.definitions()


@dataclass(frozen=True)
class Union(Value):
    """The several values a name may hold, one per branch that binds it."""

    values: tuple[Value, ...]

    @property
    def kind(self) -> str:
        return self.values[0].kind

    @property
    def description(self) -> str:
        return " | ".join(value.description for value in self.values)

    def attributes(self) -> list[Symbol]:
        return _merge(*(value.attributes() for value in self.values))

    def attribute(self, name: str) -> Value | None:
        found = [attribute for value in self.values
                 if (attribute := value.attribute(name)) is not None]
        return union(found) if found else None

    def definitions(self) -> list[Definition]:
        return [definition for value in self.values for definition in value.definitions()]


def union(values: Iterable[Value]) -> Value:
    """One value standing for all of ``values``; unknowns and repeats drop out."""
    members: list[Value] = []
    for value in values:
        for member in value.values if isinstance(value, Union) else [value]:
            if not isinstance(member, Unknown) and member not in members:
                members.append(member)
    if not members:
        return UNKNOWN
    return members[0] if len(members) == 1 else Union(tuple(members))


@dataclass(frozen=True)
class RuntimeObject(Value):
    """A live Python object reached through an actual import.

    ``public_only`` is set for modules, whose spec'd attribute set is limited to
    names that do not start with an underscore.  For an instance ``obj`` is the
    class, since that is what carries the attributes.
    """

    obj: object
    name: str
    kind: str
    description: str
    public_only: bool = False

    def attributes(self) -> list[Symbol]:
        names = dir(self.obj)
        if self.public_only:
            names = [name for name in names if not name.startswith("_")]
        return [Symbol(name, runtime_value(getattr(self.obj, name, None), name)) for name in names]

    def definitions(self) -> list[Definition]:
        """Imported objects are outside the project: they report no position."""
        return [Definition(self.name, self.kind, self._full_name(), "", 0, 0,
                           self.description, inspect.getdoc(self.obj) or "")]

    def _full_name(self) -> str:
        if self.kind == "module":
            return getattr(self.obj, "__name__", self.name)
        module = getattr(self.obj, "__module__", "")
        return ".".join(part for part in (module, self.name) if part)


def runtime_value(obj: object, label: str) -> Value:
    """Classify a live object into the value that describes it."""
    if inspect.ismodule(obj):
        return RuntimeObject(obj, label, "module", f"module {label}", public_only=True)
    if inspect.isclass(obj):
        return RuntimeObject(obj, obj.__name__, "class", f"class {obj.__name__}")
    if callable(obj):
        return RuntimeObject(obj, label, "function", f"def {label}(...)")
    return runtime_instance(type(obj))


def runtime_instance(cls: type) -> Value:
    """An instance of a live class; its attributes are the class' attributes."""
    name = "None" if cls is type(None) else cls.__name__
    return RuntimeObject(cls, name, "instance", f"instance of {name}")


NONE = runtime_instance(type(None))


@dataclass(frozen=True)
class ModuleRef(Value):
    """A module named in a listing, loaded only when something is asked of it.

    Offering every module a package holds must not parse them all, so a
    reference carries the name a completion shows and defers the rest.
    """

    dotted: str
    load: Callable[[], Value | None]
    kind = "module"

    @property
    def description(self) -> str:
        return f"module {self.dotted}"

    def attributes(self) -> list[Symbol]:
        return self._loaded().attributes()

    def symbol(self, name: str) -> Symbol | None:
        return self._loaded().symbol(name)

    def definitions(self) -> list[Definition]:
        return self._loaded().definitions()

    def _loaded(self) -> Value:
        return self.load() or UNKNOWN


@dataclass(frozen=True)
class SourceModule(Value):
    """A module of the project that was parsed rather than imported.

    ``exported`` is what ``__all__`` declares, or ``None`` when the module
    declares no ``__all__``; ``submodules`` are the modules a package holds,
    which are importable from it whether or not its body mentions them.
    """

    scope: Scope
    site: Definition
    exported: tuple[str, ...] | None
    submodules: Callable[[], list[Symbol]]
    kind = "module"

    @property
    def description(self) -> str:
        return self.site.description

    def attributes(self) -> list[Symbol]:
        """The public names: ``__all__`` when declared, else the non-underscore ones."""
        public = {binding.name: binding for binding in self.scope.bindings
                  if self._public(binding.name)}
        return _merge(_symbols(public.values()), self.submodules())

    def symbol(self, name: str) -> Symbol | None:
        """Any name the module body binds, private ones included, then its modules."""
        bound = [binding for binding in self.scope.bindings if binding.name == name]
        if bound:
            return Symbol(name, bound[-1].value(), bound[-1])
        return next((symbol for symbol in self.submodules() if symbol.name == name), None)

    def definitions(self) -> list[Definition]:
        return [self.site]

    def _public(self, name: str) -> bool:
        return not name.startswith("_") if self.exported is None else name in self.exported


@dataclass(frozen=True)
class SourceFunction(Value):
    """A ``def`` or ``lambda`` in parsed source.

    ``returns`` is what a call to it evaluates to, deferred because inferring
    it means walking a body that may call back into this function.
    """

    site: Definition
    returns: Lazy
    kind = "function"

    @property
    def name(self) -> str:
        return self.site.name

    @property
    def description(self) -> str:
        return f"def {self.name}(...)"

    def attributes(self) -> list[Symbol]:
        return runtime_instance(types.FunctionType).attributes()

    def definitions(self) -> list[Definition]:
        return [self.site]


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

    site: Definition
    scope: Scope
    bases: Callable[[], list[Value]]
    self_attributes: list[Binding]
    kind = "class"

    @property
    def name(self) -> str:
        return self.site.name

    @property
    def description(self) -> str:
        return f"class {self.name}"

    def definitions(self) -> list[Definition]:
        return [self.site]

    @_non_recursive
    def attributes(self) -> list[Symbol]:
        inherited = [symbol for base in self.bases() for symbol in base.attributes()]
        return _merge(_symbols(self.scope.bindings), inherited)

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

    def definitions(self) -> list[Definition]:
        """An instance points at its class, reported as an instance of it."""
        return [replace(self.cls.site, type=self.kind, description=self.description)]


def _symbols(bindings: Iterable[Binding]) -> list[Symbol]:
    return [Symbol(binding.name, binding.value(), binding) for binding in bindings]


def _merge(*groups: Iterable[Symbol]) -> list[Symbol]:
    """Concatenate symbol groups, keeping the first binding of each name."""
    merged: dict[str, Symbol] = {}
    for group in groups:
        for symbol in group:
            merged.setdefault(symbol.name, symbol)
    return list(merged.values())
