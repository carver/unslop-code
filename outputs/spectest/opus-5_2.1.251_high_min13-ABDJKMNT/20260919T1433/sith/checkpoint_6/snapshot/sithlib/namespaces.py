"""Values an interpreter holds, described by the `--namespaces` file.

Interpreter mode answers for names static analysis cannot resolve. Each
namespace object maps a name to a description of the value the interpreter
has bound to it, and the first namespace carrying a name is the one that
answers for it.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .definitions import Definition, qualified
from .runtime import Value
from .source import SourceError
from .symbols import INSTANCE, Symbol

RUNTIME = "{type} (runtime)"
ATTRIBUTE_KIND = INSTANCE
"""What an attribute a namespace only names is reported as."""


@dataclass(frozen=True)
class RuntimeName:
    """One name a namespace holds, as the namespaces file describes it."""

    key: str
    type: str
    value: str = ""
    """String form of the value, which stands in for a docstring."""
    module: str = ""
    name: str = ""
    """The name the value carries itself, when it differs from the key."""
    attributes: Tuple[str, ...] = ()

    @property
    def description(self) -> str:
        return RUNTIME.format(type=self.type)


class NamespaceValue(Value):
    """A value known only from the namespace that describes it."""

    def __init__(self, described: RuntimeName):
        self.described = described
        self.kind = described.type
        self.label = described.type

    def members(self) -> List[Symbol]:
        """The attributes the namespace names, whose own types it does not."""
        return [
            Symbol(name, ATTRIBUTE_KIND, described=RUNTIME.format(type=ATTRIBUTE_KIND))
            for name in self.described.attributes
        ]

    def definitions(self) -> List[Definition]:
        """A definition standing where the interpreter holds the value."""
        name = self.described.name or self.described.key
        return [Definition(
            name=name,
            type=self.described.type,
            full_name=qualified(self.described.module, name),
            module_path="",
            line=0,
            column=0,
            description=self.described.description,
            docstring=self.described.value,
        )]


class Namespaces:
    """The namespaces a command falls back to, searched in order."""

    def __init__(self, entries: Optional[Dict[str, RuntimeName]] = None):
        self.entries = entries or {}

    def symbol(self, name: str) -> Optional[Symbol]:
        """What the namespaces say a name holds, if any of them do."""
        entry = self.entries.get(name)
        return runtime_symbol(entry) if entry is not None else None

    def value_of(self, expression: ast.expr) -> Optional[Value]:
        """What the namespaces say a written name holds, if it is a bare name."""
        symbol = self.symbol(expression.id) if isinstance(expression, ast.Name) else None
        return symbol.value if symbol is not None else None

    def absent_from(self, taken: Iterable[str]) -> List[Symbol]:
        """The runtime names that static analysis has no binding for."""
        known = set(taken)
        return [
            runtime_symbol(entry) for name, entry in self.entries.items() if name not in known
        ]


def runtime_symbol(entry: RuntimeName) -> Symbol:
    """A namespace entry as a completable symbol."""
    return Symbol(entry.key, entry.type, value=NamespaceValue(entry), described=entry.description)


def load_namespaces(path) -> Namespaces:
    """Read a namespaces file, keeping the first description of each name."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        entries: Dict[str, RuntimeName] = {}
        for namespace in document:
            for key, described in namespace.items():
                entries.setdefault(key, _entry(key, described))
    except (OSError, UnicodeDecodeError, ValueError, AttributeError, TypeError) as error:
        raise SourceError(f"cannot read namespaces file {path}: {error}") from error
    return Namespaces(entries)


def _entry(key: str, described: Dict) -> RuntimeName:
    """One name of a namespace, with the fields the file left out defaulted."""
    return RuntimeName(
        key=key,
        type=str(described.get("type", "")),
        value=str(described.get("value", "")),
        module=str(described.get("module", "")),
        name=str(described.get("name", "")),
        attributes=tuple(described.get("attributes", ())),
    )
