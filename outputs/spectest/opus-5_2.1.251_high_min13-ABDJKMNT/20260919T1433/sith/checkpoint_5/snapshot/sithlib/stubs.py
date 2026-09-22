"""Type information taken from `.pyi` stub files.

A stub describes a module that is written elsewhere: the annotations are the
stub's, while the names, positions and docstrings a user navigates to belong
to the runtime module. A :class:`Stubbed` value holds both halves together so
that `infer`, `complete` and `signatures` read the stub while `goto` keeps
landing in the source.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterator, List, Optional

from .runtime import Value
from .symbols import CLASS, FUNCTION, MODULE, Symbol

ENTITIES = {CLASS, FUNCTION, MODULE}
"""Kinds a stub and a source file describe the same definition of."""

STUB_SUFFIX = ".pyi"
STUB_PACKAGE = "__init__.pyi"
STUB_DIRECTORY = "stubs"


def stub_candidates(root: Path, dotted: str) -> Iterator[Path]:
    """Where a module's stub may live, in the order the spec searches.

    An inline stub written beside the module comes first, then the project's
    own ``stubs/`` directory, either as a file or as a stub package.
    """
    parts = dotted.split(".")
    inline = root.joinpath(*parts)
    yield inline.with_suffix(STUB_SUFFIX)
    yield inline / STUB_PACKAGE
    collected = root.joinpath(STUB_DIRECTORY, *parts)
    yield collected.with_suffix(STUB_SUFFIX)
    yield collected / STUB_PACKAGE


class Stubbed(Value):
    """A definition a stub gives the type of and a source file the body of."""

    def __init__(self, typed: Value, source: Value):
        self.typed = typed
        """The half read from the stub, which decides types."""
        self.source = source
        """The half read from the runtime module, which decides positions."""
        self.kind = typed.kind
        self.label = typed.label

    def members(self) -> List[Symbol]:
        """Stub members placed at their source definitions, source-only names kept."""
        described = {symbol.name: symbol for symbol in self.source.members()}
        stubbed = [
            stubbed_symbol(described.pop(symbol.name, None), symbol)
            for symbol in self.typed.members()
        ]
        return stubbed + list(described.values())

    def attributes(self, name: str) -> List[Symbol]:
        described = self.source.attributes(name)
        stubbed = self.typed.attributes(name)
        if not stubbed:
            return described
        return [
            stubbed_symbol(described[0] if described else None, symbol) for symbol in stubbed
        ]

    def instance(self) -> Optional[Value]:
        return stubbed_value(self.typed.instance(), self.source.instance())

    def called(self, depth: int = 0) -> Optional[Value]:
        """Calling a stubbed class builds an instance; anything else asks the stub."""
        if self.kind == CLASS:
            return self.instance()
        return self.typed.called(depth)

    def definitions(self):
        return self.source.definitions()


def stubbed_value(typed: Optional[Value], source: Optional[Value]) -> Optional[Value]:
    """A stubbed value, or whichever half of it is known."""
    if typed is None or source is None:
        return typed if typed is not None else source
    return Stubbed(typed, source)


def stubbed_symbol(described: Optional[Symbol], stubbed: Symbol) -> Symbol:
    """A stub binding reported at the source definition it describes."""
    if described is None:
        return stubbed
    return replace(described, kind=stubbed.kind, label=stubbed.label, value=_typed(described, stubbed))


def _typed(described: Symbol, stubbed: Symbol) -> Optional[Value]:
    """The value a merged binding holds.

    A stub and a module declare the same functions, classes and modules, so
    those keep both halves; anything else the stub annotates is a type it
    states outright, which stands in for whatever was inferred.
    """
    if stubbed.kind in ENTITIES:
        return stubbed_value(stubbed.value, described.value)
    return stubbed.value if stubbed.value is not None else described.value


def source_half(value: Optional[Value]) -> Optional[Value]:
    """The half of a value that is backed by runtime source, stub or not."""
    return value.source if isinstance(value, Stubbed) else value
