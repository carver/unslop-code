"""The live values an interpreter session offers, read from a `--namespaces` file.

A namespace is a JSON object mapping a name to a description of the value
bound to it at runtime.  The file lists namespaces in the order they should be
searched, and static analysis is always consulted first: what is written here
only answers for names the source itself cannot explain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .definitions import Definition
from .source import SithError
from .symbols import Symbol


@dataclass(frozen=True)
class RuntimeValue:
    """One name bound in a live namespace, as the file describes it."""

    key: str
    type: str
    value: str = ""
    module: str = ""
    name: str = ""
    attributes: tuple[str, ...] = ()

    @classmethod
    def of(cls, key: str, described: dict) -> "RuntimeValue":
        return cls(
            key=key,
            type=described.get("type", ""),
            value=described.get("value", ""),
            module=described.get("module", ""),
            name=described.get("name", ""),
            attributes=tuple(described.get("attributes") or ()),
        )

    @property
    def description(self) -> str:
        """How a runtime value is described wherever it is reported."""
        return f"{self.type} (runtime)"

    @property
    def full_name(self) -> str:
        """The name the value answers to, qualified by the module it came from."""
        name = self.name or self.key
        return f"{self.module}.{name}" if self.module and self.module != name else name

    def symbol(self) -> Symbol:
        return Symbol(self.key, self.type, self.description)

    def attribute_symbols(self) -> list[Symbol]:
        """The attributes the file lists, which carry the type of their owner."""
        return [Symbol(name, self.type, self.description) for name in self.attributes]

    def definition(self) -> Definition:
        """A definition record for a value that exists only at runtime."""
        return Definition(
            name=self.name or self.key,
            kind=self.type,
            full_name=self.full_name,
            module_path="",
            line=0,
            column=0,
            description=self.description,
            docstring=self.value,
        )


@dataclass(frozen=True)
class Namespaces:
    """The namespaces of one request, flattened so that the first match wins."""

    values: dict[str, RuntimeValue] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "Namespaces":
        values: dict[str, RuntimeValue] = {}
        for namespace in _read(path):
            for key, described in namespace.items():
                values.setdefault(key, RuntimeValue.of(key, described))
        return cls(values)

    def symbols(self) -> list[Symbol]:
        """Every runtime name, as a completion candidate."""
        return [value.symbol() for value in self.values.values()]

    def attributes(self, receiver: str) -> list[Symbol]:
        """The attributes of a runtime value, offered after a dot."""
        value = self.values.get(receiver)
        return value.attribute_symbols() if value else []

    def definitions(self, name: str) -> list[Definition]:
        """What a name is worth at runtime, for `infer` and `goto` to fall back on."""
        value = self.values.get(name)
        return [value.definition()] if value else []


def _read(path: str) -> list[dict]:
    """The namespaces a file holds, refusing anything but an array of objects."""
    try:
        text = open(path, "rb").read().decode("utf-8")
        found = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SithError(f"cannot read namespaces {path}: {error}") from error
    if not isinstance(found, list) or not all(_is_namespace(entry) for entry in found):
        raise SithError(f"namespaces {path}: expected an array of namespace objects")
    return found


def _is_namespace(entry: object) -> bool:
    return isinstance(entry, dict) and all(isinstance(v, dict) for v in entry.values())
