"""Type aliases: the spellings a schema may use in place of a canonical type.

A handful of aliases are always available — ``integer``, ``double``, ``list``
and friends — and ``--type-alias-file`` adds more.  Names are matched after
lowercasing and may chain (an alias pointing at another alias), so the table is
checked for cycles up front rather than while a schema is being read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from .coltypes import ColumnType
from .errors import SchemaError, UsageError

#: Type names that end a resolution chain.  ``struct``, ``array`` and ``map``
#: name the nested kinds; the primitives are everything :class:`ColumnType`
#: knows.  ``json`` is deliberately absent: it is an alias for ``struct``.
CANONICAL_TYPES = frozenset(
    {"struct", "array", "map"} | {member.value for member in ColumnType}
)

#: Aliases every run understands, whether or not an alias file is given.
BUILTIN_ALIASES = {
    "integer": "int",
    "long": "int",
    "double": "float",
    "number": "float",
    "boolean": "bool",
    "datetime": "timestamp",
    "timestamptz": "timestamp",
    "text": "string",
    "varchar": "string",
    "list": "array",
    "json": "struct",
}


@dataclass(frozen=True)
class AliasTable:
    """Resolves a written type name to the canonical name it stands for."""

    entries: Mapping[str, str]

    def resolve(self, name: str) -> str:
        """Follow ``name`` through the alias chain, case-insensitively.

        A name that is already canonical is returned as it is, and one that no
        alias covers is returned unchanged so the caller can report it as
        unknown with the spelling the user wrote.
        """
        resolved = name.strip().lower()
        while resolved not in CANONICAL_TYPES and resolved in self.entries:
            resolved = self.entries[resolved]
        return resolved


def load_aliases(path: str | None) -> AliasTable:
    """Build the alias table, extending the built-ins with an optional file."""
    entries = dict(BUILTIN_ALIASES)
    if path is not None:
        entries.update(_read(path))
    for name in entries:
        _walk(name, entries)
    return AliasTable(entries)


def _read(path: str) -> dict[str, str]:
    """Read ``{"aliases": {...}}`` from an alias file, lowercasing both sides."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path}: invalid JSON: {error}") from error
    aliases = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(aliases, dict):
        raise SchemaError(f"{path}: expected an 'aliases' object")
    if not all(isinstance(target, str) for target in aliases.values()):
        raise SchemaError(f"{path}: every alias must name a type as a string")
    return {name.lower(): target.strip().lower() for name, target in aliases.items()}


def _walk(name: str, entries: Mapping[str, str]) -> None:
    """Follow one alias chain to its end, reporting a cycle instead of looping."""
    seen = [name]
    current = name
    while current not in CANONICAL_TYPES and current in entries:
        current = entries[current]
        if current in seen:
            raise UsageError(f"alias cycle: {' -> '.join(seen + [current])}")
        seen.append(current)
