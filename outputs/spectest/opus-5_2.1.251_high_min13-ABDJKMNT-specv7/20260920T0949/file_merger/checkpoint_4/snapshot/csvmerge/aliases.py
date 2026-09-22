"""Type aliases: the built-in table, ``--type-alias-file``, and their resolution.

A declared type name is lowercased and then followed through the alias table
until it reaches a name the type parser knows. Primitive and nested kind names
are terminal, so no alias file can redefine ``int`` or ``array``; every other
name may be aliased, transitively, as long as the chains do not loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .casting import TYPES
from .errors import ToolError, UsageError

#: The kinds a resolved name can name besides the six primitives.
KIND_NAMES = ("struct", "array", "map")

#: Terminal names: an alias chain stops as soon as it reaches one of these.
TERMINAL_NAMES = frozenset(TYPES) | frozenset(KIND_NAMES)

#: Always present, whether or not an alias file is given.
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
    # A field declared `json` is a struct with no declared fields: any JSON.
    "json": "struct",
}


@dataclass(frozen=True)
class Aliases:
    """A resolved alias table, already lowercased and checked for cycles."""

    table: dict[str, str]

    def resolve(self, name: str) -> str:
        """Follow ``name`` through the table to the terminal name it stands for."""
        lowered = name.strip().lower()
        while lowered not in TERMINAL_NAMES and lowered in self.table:
            lowered = self.table[lowered]
        return lowered


def load_aliases(path: str | None) -> Aliases:
    """Build the alias table, adding the entries of ``--type-alias-file`` to it."""
    table = dict(BUILTIN_ALIASES)
    if path is not None:
        table.update(_user_aliases(path))
    for name in table:
        _walk(name, table, path)
    return Aliases(table)


def _user_aliases(path: str) -> dict[str, str]:
    """Read the ``aliases`` object of an alias file, lowercasing both halves."""
    with open(path, encoding="utf-8") as handle:
        try:
            document = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ToolError(f"{path}: invalid JSON ({exc})") from None

    aliases = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(aliases, dict):
        raise ToolError(f"{path}: expected an 'aliases' object")
    if not all(isinstance(target, str) for target in aliases.values()):
        raise ToolError(f"{path}: every alias must name a type")
    return {name.lower(): target.strip().lower() for name, target in aliases.items()}


def _walk(name: str, table: dict[str, str], path: str | None) -> None:
    """Follow one chain from ``name``, reporting a loop as error 2."""
    seen = {name}
    current = name
    while current not in TERMINAL_NAMES and current in table:
        current = table[current]
        if current in seen:
            source = path or "the built-in aliases"
            raise UsageError(f"{source}: type alias {name!r} resolves in a cycle")
        seen.add(current)
