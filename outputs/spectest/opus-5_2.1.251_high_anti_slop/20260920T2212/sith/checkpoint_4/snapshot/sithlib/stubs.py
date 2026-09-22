"""Type information read from ``.pyi`` stub files.

A stub says what a module's functions and classes look like; the ``.py`` file
next to it says where they were written.  :class:`Stubbed` keeps both, taking
everything about the type from the stub -- which is why the stub exists -- and
every position from the implementation, so that navigation still lands in real
source.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .definitions import Definition
from .signatures import Signature
from .values import SourceModule, Symbol, Value


def stub_path(root: Path, dotted: str) -> Path | None:
    """The ``.pyi`` file describing module ``dotted``, if the project ships one.

    An inline stub, written beside the implementation, wins over one collected
    in the project's ``stubs`` directory.
    """
    parts = dotted.split(".")
    candidates = (root.joinpath(*parts).with_suffix(".pyi"),
                  root.joinpath(*parts, "__init__.pyi"),
                  root.joinpath("stubs", *parts).with_suffix(".pyi"),
                  root.joinpath("stubs", *parts, "__init__.pyi"))
    return next((path for path in candidates if path.is_file()), None)


def implemented(module: Value | None) -> dict[str, Definition]:
    """Where the ``.py`` file writes each name its stub may also declare.

    A stub is parsed with this map in hand, so every record it produces already
    points at real source.  A name the stub declares and the file does not keeps
    the stub's own position, which is the only one it has.
    """
    if not isinstance(module, SourceModule):
        return {}
    written = {binding.site.full_name: binding.site
               for scope in module.scope.descendants()
               for binding in scope.bindings}
    return {module.site.full_name: module.site, **written}


def relocate(declared: Definition, written: Definition | None) -> Definition:
    """A stub's record placed where the implementation writes the same name."""
    if written is None:
        return declared
    return replace(declared, module_path=written.module_path, line=written.line,
                   column=written.column, docstring=declared.docstring or written.docstring)


@dataclass(frozen=True)
class Stubbed(Value):
    """A value a stub declares and a ``.py`` file implements."""

    stub: Value
    runtime: Value

    @property
    def kind(self) -> str:
        return self.stub.kind

    @property
    def description(self) -> str:
        return self.stub.description

    def attributes(self) -> list[Symbol]:
        """Every declared name paired with its implementation, then the rest."""
        written = {symbol.name: symbol for symbol in self.runtime.attributes()}
        paired = [_pair(symbol, written.pop(symbol.name, None))
                  for symbol in self.stub.attributes()]
        return paired + list(written.values())

    def symbol(self, name: str) -> Symbol | None:
        declared = self.stub.symbol(name)
        written = self.runtime.symbol(name)
        return _pair(declared, written) if declared is not None else written

    def signatures(self) -> list[Signature]:
        return self.stub.signatures() or self.runtime.signatures()

    def instantiated(self) -> Value:
        return Stubbed(self.stub.instantiated(), self.runtime.instantiated())

    def definitions(self) -> list[Definition]:
        """What the stub declares, which was already placed in real source."""
        return self.stub.definitions() or self.runtime.definitions()


def _pair(declared: Symbol, written: Symbol | None) -> Symbol:
    """One name as the stub declares it and the implementation writes it.

    The implementation's binding is kept, because that is what ``goto`` reports
    and where following an import leads.
    """
    if written is None:
        return declared
    return Symbol(declared.name, Stubbed(declared.value, written.value), written.binding)
