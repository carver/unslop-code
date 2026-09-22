"""The live namespaces interpreter mode falls back to.

A REPL knows things the source does not: which names the session has already
bound and what they hold.  ``--namespaces`` hands that over as JSON, one object
per namespace, and the values it describes are offered wherever static analysis
comes up empty.  Nothing here is executed -- a namespace entry is a description
of a runtime value, not the value itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .definitions import Definition
from .errors import SithError
from .signatures import Signature
from .values import UNKNOWN, Symbol, Value

_CALLABLE = ("function", "class")


@dataclass(frozen=True)
class RuntimeValue(Value):
    """A value that exists only in a live namespace.

    ``key`` is the name the namespace binds, ``original`` the name the value
    carries when it differs, and ``text`` the string representation the
    namespace supplied, which stands in for a docstring.
    """

    key: str
    type: str
    text: str = ""
    module: str = ""
    original: str = ""
    members: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return self.type

    @property
    def description(self) -> str:
        return f"{self.type} (runtime)"

    @property
    def name(self) -> str:
        return self.original or self.key

    def attributes(self) -> list[Symbol]:
        """The attributes the namespace listed, whose own types are unknown."""
        return [Symbol(member, RuntimeValue(member, "instance")) for member in self.members]

    def definitions(self) -> list[Definition]:
        """A runtime value was never written down, so it reports no position."""
        full_name = ".".join(part for part in (self.module, self.name) if part)
        return [Definition(self.name, self.type, full_name, "", 0, 0,
                           self.description, self.text)]

    def signatures(self) -> list[Signature]:
        """A runtime callable is known by name only: its parameters are not."""
        return [Signature(self.name, docstring=self.text)] if self.type in _CALLABLE else []

    def instantiated(self) -> Value:
        """Calling a runtime class yields an instance carrying its attributes."""
        return replace(self, type="instance") if self.type == "class" else UNKNOWN


@dataclass(frozen=True)
class Namespaces:
    """The namespaces of a session, searched in the order they were given."""

    groups: tuple[dict[str, RuntimeValue], ...] = ()

    @classmethod
    def load(cls, path: Path) -> "Namespaces":
        """Read a namespaces file: a JSON array of ``{name: description}`` objects."""
        if not path.is_file():
            raise SithError(f"not a regular file: {path}")
        try:
            listed = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SithError(f"not a valid namespaces file: {path} ({error})") from error
        if not isinstance(listed, list):
            raise SithError(f"expected a JSON array of namespaces in {path}")
        return cls(tuple(_namespace(entry, path) for entry in listed))

    def value(self, name: str) -> RuntimeValue | None:
        """What the first namespace holding ``name`` says it is."""
        return next((group[name] for group in self.groups if name in group), None)

    def symbols(self) -> list[Symbol]:
        """Every name the namespaces bind, the first binding of each winning."""
        merged: dict[str, RuntimeValue] = {}
        for group in self.groups:
            for name, value in group.items():
                merged.setdefault(name, value)
        return [Symbol(name, value) for name, value in merged.items()]


def _namespace(entry: object, path: Path) -> dict[str, RuntimeValue]:
    if not isinstance(entry, dict):
        raise SithError(f"expected a JSON object per namespace in {path}")
    return {name: _value(name, fields, path) for name, fields in entry.items()}


def _value(name: str, fields: object, path: Path) -> RuntimeValue:
    """One ``{"type": ..., "value": ...}`` description of a runtime value."""
    if not isinstance(fields, dict) or not isinstance(fields.get("type"), str):
        raise SithError(f"namespace entry {name!r} of {path} needs a string 'type'")
    return RuntimeValue(name, fields["type"], str(fields.get("value", "")),
                        str(fields.get("module", "")), str(fields.get("name", "")),
                        tuple(fields.get("attributes", ())))
