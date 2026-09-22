"""Resolving the output schema, either from a JSON file or by inference.

A schema file fixes the columns, their order and their types, which may be
nested; inference instead asks every input which types fit each of its
columns - always flat ones - and settles the disagreements between them with
the chosen ``--schema-strategy``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Sequence

from csvmerge.aliases import Aliases
from csvmerge.paths import FieldPath, resolve_path
from csvmerge.sources import Source
from csvmerge.types import DataType, Primitive, parse_type
from csvmerge.values import best_type

AUTHORITATIVE = "authoritative"
CONSENSUS = "consensus"
UNION = "union"
STRATEGIES = (AUTHORITATIVE, CONSENSUS, UNION)

# One file's opinion on a column: whether the format carries its own types,
# and the types that fit every value it holds.
_Opinion = tuple[bool, FrozenSet[str]]


@dataclass(frozen=True)
class Column:
    name: str
    type: DataType


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def paths_of(self, wanted: Sequence[str], role: str) -> tuple[FieldPath, ...]:
        """Resolve field paths against these columns, each ending on a primitive.

        ``role`` names what the paths are for - ``key`` or ``partition`` - and
        only appears in error messages.
        """
        return tuple(resolve_path(text, self.columns, role) for text in wanted)


def load_schema(path: str, aliases: Aliases) -> Schema:
    """Read an explicit schema definition, which fixes both types and column order."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return Schema(
        tuple(
            Column(entry["name"], parse_type(entry["type"], aliases, f"column {entry['name']!r}"))
            for entry in document["columns"]
        )
    )


def infer_schema(sources: Sequence[Source], mode: str, strategy: str) -> Schema:
    """Infer the schema from the union of the input columns, in lexicographic order.

    A column a file does not carry, or carries without ever filling, is not an
    opinion about its type. When no file has an opinion at all the column
    falls back to ``string``.
    """
    opinions: dict[str, list[_Opinion]] = {}
    for source in sources:
        for name, candidates in source.observe_types(mode).items():
            seen = opinions.setdefault(name, [])
            if candidates is not None:
                seen.append((source.typed, candidates))
    resolve = _STRATEGIES[strategy]
    return Schema(
        tuple(Column(name, Primitive(resolve(opinions[name]))) for name in sorted(opinions))
    )


def _authoritative(opinions: Sequence[_Opinion]) -> str:
    """Take the type of the first source that carries types of its own."""
    for typed, candidates in opinions:
        if typed:
            return best_type(candidates)
    return _union(opinions)


def _consensus(opinions: Sequence[_Opinion]) -> str:
    """Take the type the most files resolve to on their own.

    A file votes with the type it would give the column by itself, so the
    majority can outvote a minority whose values the winner cannot hold -
    those cells then follow ``--on-type-error``. Ties go to the most
    specific type.
    """
    votes = Counter(best_type(candidates) for _, candidates in opinions)
    if not votes:
        return best_type(None)
    winning = max(votes.values())
    return best_type(frozenset(name for name, count in votes.items() if count == winning))


def _union(opinions: Sequence[_Opinion]) -> str:
    """Take the most specific type that fits every value every file holds."""
    common: FrozenSet[str] | None = None
    for _, candidates in opinions:
        common = candidates if common is None else common & candidates
    return best_type(common)


_STRATEGIES = {AUTHORITATIVE: _authoritative, CONSENSUS: _consensus, UNION: _union}
