"""Type aliases: the built-in spellings, and the ones ``--type-alias-file`` adds.

An alias is a lower-case name standing for another type name - or for a whole
type expression, as ``intlist`` might stand for ``array<int>``. Aliases chain,
so resolving one keeps following the table until it reaches a name the table
does not define; a chain that returns to a name it has already visited is a
cycle and is refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from csvmerge.errors import EXIT_USAGE, MergeError

# Always available, whatever the alias file says. ``list`` is the head of
# ``list<T>``, and ``json`` reaches a field-less ``struct``, which is the type
# that accepts any JSON value.
BUILTIN_ALIASES: Mapping[str, str] = {
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
class Aliases:
    """The alias table, looked up case-insensitively."""

    table: Mapping[str, str]

    def resolve(self, name: str, seen: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        """Follow ``name`` through the table until it names something else.

        Returns what it ended up at - a type name, or a whole type expression
        such as ``array<int>`` - along with the aliases followed to get there.
        ``seen`` holds the aliases followed earlier, through this chain or
        through an expression an outer alias expanded into, so a cycle is
        caught wherever it closes.
        """
        current = name.strip().lower()
        while current in self.table:
            if current in seen:
                raise MergeError(
                    f"type alias {current!r} is defined in terms of itself: "
                    f"{' -> '.join((*seen, current))}",
                    EXIT_USAGE,
                )
            seen += (current,)
            current = self.table[current].strip().lower()
        return current, seen


def load_aliases(path: str | None) -> Aliases:
    """Read an alias file, if one was given, on top of the built-in aliases."""
    table = dict(BUILTIN_ALIASES)
    if path:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        table.update(
            {name.strip().lower(): target for name, target in document["aliases"].items()}
        )
    return Aliases(table)
