"""Resolving the output schema, either from a JSON file or by inference."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from .csvio import open_csv, read_header
from .dialect import CsvDialect
from .errors import MergeError
from .types import TYPE_PRIORITY, ColumnType, matching_types


class InferMode(str, Enum):
    """How aggressively to infer types when no schema file is supplied."""

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
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def index_of(self, name: str) -> int:
        """Return the output position of ``name``, or raise if it is absent."""
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        raise MergeError(f"key column {name!r} is not present in the resolved schema")


def load_schema(path: str) -> Schema:
    """Load an explicit schema: ``{"columns": [{"name": ..., "type": ...}, ...]}``."""
    with open(path, encoding="utf-8") as stream:
        try:
            document = json.load(stream)
        except json.JSONDecodeError as error:
            raise MergeError(f"{path}: invalid JSON ({error})") from error
    entries = document.get("columns")
    if not isinstance(entries, list) or not entries:
        raise MergeError(f"{path}: schema must contain a non-empty 'columns' list")
    return Schema(tuple(_parse_column(entry, path) for entry in entries))


def infer_schema(paths: Sequence[str], dialect: CsvDialect, mode: InferMode) -> Schema:
    """Infer a schema from the union of the input headers, ordered lexicographically.

    ``strict`` resolves a type per file and falls back to ``string`` when files
    disagree; a blank cell is an observation that only ``string`` satisfies.
    ``loose`` ignores blanks entirely and unifies all files at once, so a column
    holding ints in one file and floats in another still resolves to ``float``.
    """
    names = sorted({name for path in paths for name in read_header(path, dialect)})
    ignore_nulls = mode is InferMode.LOOSE
    per_file = [_scan_candidates(path, dialect, ignore_nulls) for path in paths]
    resolve = _resolve_loose if mode is InferMode.LOOSE else _resolve_strict
    return Schema(tuple(Column(name, resolve([scan.get(name) for scan in per_file])) for name in names))


def _parse_column(entry: dict, path: str) -> Column:
    try:
        return Column(entry["name"], ColumnType(entry["type"]))
    except (KeyError, TypeError) as error:
        raise MergeError(f"{path}: every schema column needs a 'name' and a 'type'") from error
    except ValueError as error:
        supported = ", ".join(column_type.value for column_type in ColumnType)
        raise MergeError(f"{path}: unknown type {entry['type']!r} (expected one of: {supported})") from error


def _scan_candidates(path: str, dialect: CsvDialect, ignore_nulls: bool) -> dict[str, set[ColumnType]]:
    """Intersect the types accepted by every observed cell, per column of one file."""
    candidates: dict[str, set[ColumnType]] = {}
    with open_csv(path, dialect) as (header, rows):
        for row in rows:
            for name, text in zip(header, row):
                if ignore_nulls and dialect.is_null(text):
                    continue
                observed = candidates.get(name)
                matches = matching_types(text)
                candidates[name] = matches if observed is None else observed & matches
    return candidates


def _resolve_loose(per_file: Iterable[set[ColumnType] | None]) -> ColumnType:
    observed = [candidates for candidates in per_file if candidates is not None]
    if not observed:
        return ColumnType.STRING
    return _highest_priority(set.intersection(*observed))


def _resolve_strict(per_file: Iterable[set[ColumnType] | None]) -> ColumnType:
    types = {_highest_priority(candidates) for candidates in per_file if candidates is not None}
    if len(types) == 1:
        return types.pop()
    return ColumnType.STRING


def _highest_priority(candidates: set[ColumnType]) -> ColumnType:
    return next(column_type for column_type in TYPE_PRIORITY if column_type in candidates)
