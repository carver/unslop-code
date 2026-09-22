"""Resolving the output schema, either from a JSON file or by inference.

Inference asks every input which types fit each of its columns, then settles
the disagreements between them with the chosen ``--schema-strategy``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Sequence

from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.sources import Source
from csvmerge.values import TYPE_PRIORITY, best_type

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
    type: str


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def indexes_of(self, wanted: Sequence[str], role: str) -> tuple[int, ...]:
        """Locate the named columns, rejecting any the schema does not define.

        ``role`` names what the columns are for - ``key`` or ``partition`` -
        and only appears in the error message.
        """
        names = self.names
        missing = [name for name in wanted if name not in names]
        if missing:
            raise MergeError(
                f"{role} column(s) {', '.join(missing)} are not in the resolved schema: "
                f"{', '.join(names)}",
                EXIT_SCHEMA,
            )
        return tuple(names.index(name) for name in wanted)


def load_schema(path: str) -> Schema:
    """Read an explicit schema definition, which fixes both types and column order."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    columns = []
    for entry in document["columns"]:
        column = Column(entry["name"], entry["type"])
        if column.type not in TYPE_PRIORITY:
            raise MergeError(
                f"unknown column type {column.type!r} for column {column.name!r} in {path}", EXIT_SCHEMA
            )
        columns.append(column)
    return Schema(tuple(columns))


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
    return Schema(tuple(Column(name, resolve(opinions[name])) for name in sorted(opinions)))


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
