"""Resolving the output schema, either from a JSON file or by inference."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterable, Sequence

from csvmerge.csvio import InputDialect, open_csv
from csvmerge.errors import MergeError
from csvmerge.values import TYPE_PRIORITY, best_type, candidate_types

STRICT = "strict"
LOOSE = "loose"


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

    def key_indexes(self, key_names: Sequence[str]) -> tuple[int, ...]:
        """Locate the sort key columns, rejecting keys the schema does not define."""
        names = self.names
        missing = [name for name in key_names if name not in names]
        if missing:
            raise MergeError(
                f"key column(s) {', '.join(missing)} are not in the resolved schema: {', '.join(names)}"
            )
        return tuple(names.index(name) for name in key_names)


def load_schema(path: str) -> Schema:
    """Read an explicit schema definition, which fixes both types and column order."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    columns = []
    for entry in document["columns"]:
        column = Column(entry["name"], entry["type"])
        if column.type not in TYPE_PRIORITY:
            raise MergeError(f"unknown column type {column.type!r} for column {column.name!r} in {path}")
        columns.append(column)
    return Schema(tuple(columns))


class _TypeTracker:
    """Narrows the set of types that fit every value observed in one column."""

    def __init__(self) -> None:
        self._candidates: FrozenSet[str] | None = None

    def observe(self, text: str) -> None:
        fits = candidate_types(text)
        self._candidates = fits if self._candidates is None else self._candidates & fits

    def resolve(self) -> str:
        return best_type(self._candidates)


def infer_schema(paths: Iterable[str], dialect: InputDialect, mode: str) -> Schema:
    """Infer the schema from the union of the input headers.

    Columns come out in ascending lexicographic order. A column absent from a
    file is simply not observed there. In ``loose`` mode nulls are skipped, so
    a column parses as its numeric or temporal type as long as every real
    value does; in ``strict`` mode a null spelled as an empty cell is an
    observation like any other, and since only ``string`` accepts it, such a
    column falls back to ``string`` - as does any column whose values
    disagree across files.
    """
    trackers: dict[str, _TypeTracker] = {}
    for path in paths:
        with open_csv(path, dialect) as (header, rows):
            for name in header:
                trackers.setdefault(name, _TypeTracker())
            for row in rows:
                for name, text in zip(header, row):
                    if mode == LOOSE and dialect.is_null(text):
                        continue
                    trackers[name].observe(text)
    return Schema(tuple(Column(name, trackers[name].resolve()) for name in sorted(trackers)))
