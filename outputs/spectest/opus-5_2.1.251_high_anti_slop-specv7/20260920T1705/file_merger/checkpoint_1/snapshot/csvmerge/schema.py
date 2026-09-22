"""Resolution of the output schema: either loaded from JSON or inferred."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from .coltypes import ColumnType, candidate_types, narrowest
from .csvio import InputDialect, read_header, read_rows


class SchemaError(ValueError):
    """Raised when a schema file is malformed or a key column is unknown."""


class InferMode(str, Enum):
    """How inference treats disagreements between files."""

    STRICT = "strict"
    LOOSE = "loose"


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def positions(self, names: Iterable[str]) -> list[int]:
        """Indexes of ``names`` within the schema, rejecting unknown columns."""
        order = self.names
        unknown = [name for name in names if name not in order]
        if unknown:
            raise SchemaError(
                f"key column(s) {', '.join(unknown)} are not in the resolved schema: "
                f"{', '.join(order)}"
            )
        return [order.index(name) for name in names]


def load_schema(path: str) -> Schema:
    """Read an explicit schema definition from a JSON file."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path}: invalid JSON: {error}") from error
    definitions = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(definitions, list) or not definitions:
        raise SchemaError(f"{path}: expected a non-empty 'columns' array")
    columns = [_column_from_json(path, definition) for definition in definitions]
    names = [column.name for column in columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SchemaError(f"{path}: duplicate column(s) {', '.join(duplicates)}")
    return Schema(tuple(columns))


def _column_from_json(path: str, definition: object) -> Column:
    if not isinstance(definition, dict) or "name" not in definition or "type" not in definition:
        raise SchemaError(f"{path}: every column needs a 'name' and a 'type', got {definition!r}")
    try:
        return Column(str(definition["name"]), ColumnType(definition["type"]))
    except ValueError as error:
        raise SchemaError(
            f"{path}: unknown type {definition['type']!r}; valid types are "
            f"{', '.join(member.value for member in ColumnType)}"
        ) from error


def infer_schema(sources: Sequence[str], mode: InferMode, dialect: InputDialect) -> Schema:
    """Infer columns from the union of the input headers, ordered lexicographically.

    Every file contributes, per column, the set of types that all of its values
    match.  In ``loose`` mode those sets are intersected across files, so the
    most specific type that fits every non-null value anywhere wins.  In
    ``strict`` mode each file resolves its own column type first and any
    disagreement between files falls back to ``string``.
    """
    observed: dict[str, list[frozenset[ColumnType]]] = {}
    for source in sources:
        for name in read_header(source, dialect):
            observed.setdefault(name, [])
        for name, types in _scan(source, dialect, mode).items():
            observed[name].append(types)
    return Schema(
        tuple(Column(name, _resolve(observed[name], mode)) for name in sorted(observed))
    )


def _scan(
    source: str, dialect: InputDialect, mode: InferMode
) -> dict[str, frozenset[ColumnType]]:
    """Intersect the candidate types of every value of every column in one file.

    ``loose`` skips nulls, so they cannot widen a column.  ``strict`` treats a
    null as a value that only ``string`` accepts.
    """
    constraints: dict[str, frozenset[ColumnType]] = {}
    for row in read_rows(source, dialect):
        for name, text in row.items():
            if text is None:
                if mode is InferMode.LOOSE:
                    continue
                candidates = frozenset({ColumnType.STRING})
            else:
                candidates = candidate_types(text)
            previous = constraints.get(name)
            constraints[name] = candidates if previous is None else previous & candidates
    return constraints


def _resolve(per_file: Sequence[frozenset[ColumnType]], mode: InferMode) -> ColumnType:
    """Combine the per-file candidate sets of one column into its final type."""
    if not per_file:
        return ColumnType.STRING
    if mode is InferMode.LOOSE:
        return narrowest(frozenset.intersection(*per_file))
    per_file_types = {narrowest(candidates) for candidates in per_file}
    return per_file_types.pop() if len(per_file_types) == 1 else ColumnType.STRING
