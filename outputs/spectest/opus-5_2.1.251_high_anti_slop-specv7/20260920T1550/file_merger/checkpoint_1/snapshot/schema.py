"""Resolving the output schema, either from a JSON file or by inference."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from column_types import TYPE_PRIORITY, TYPES, ColumnType, best_type, matching_types
from csv_io import CsvOptions, Record, open_csv
from errors import MergeError

# Candidate type names per column, narrowed by every value seen so far.  Every
# value parses as a string, so a column that reaches this set cannot narrow
# further and needs no more inspection.
Candidates = dict[str, set[str]]
_STRING_ONLY = {"string"}


@dataclass(frozen=True)
class Column:
    """One column of the resolved output schema."""

    name: str
    type: ColumnType


def load_schema(path: Path) -> list[Column]:
    """Read an explicit schema: ``{"columns": [{"name": ..., "type": ...}]}``."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MergeError(f"{path}: invalid JSON ({error})") from error
    entries = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise MergeError(f"{path}: schema must be an object with a 'columns' list")

    columns = []
    for entry in entries:
        name, type_name = entry.get("name"), entry.get("type")
        if not name or not type_name:
            raise MergeError(f"{path}: every schema column needs a 'name' and a 'type'")
        if type_name not in TYPES:
            raise MergeError(f"{path}: unknown column type {type_name!r} for column {name!r}")
        columns.append(Column(name, TYPES[type_name]))
    return columns


def infer_schema(paths: Iterable[Path], options: CsvOptions, mode: str) -> list[Column]:
    """Infer the schema from the union of the input headers.

    Columns are ordered lexicographically.  In ``strict`` mode each file is
    typed on its own and columns whose files disagree fall back to ``string``;
    in ``loose`` mode the observations of all files are pooled, so a column
    that is integral in one file and fractional in another becomes ``float``.
    Null cells are ignored, and a column that is never populated is a string.
    """
    header_union: set[str] = set()
    per_file: list[Candidates] = []
    for path in paths:
        with open_csv(path, options) as (header, records):
            header_union.update(header)
            per_file.append(_scan(records, options))

    types = _pool_types(per_file) if mode == "loose" else _agreed_types(per_file)
    return [Column(name, TYPES[types.get(name, "string")]) for name in sorted(header_union)]


def _scan(records: Iterator[Record], options: CsvOptions) -> Candidates:
    """Collect the types each column of a single file is compatible with."""
    candidates: Candidates = {}
    for record in records:
        for name, text in record.items():
            if name is None or options.is_null(text):
                continue
            seen = candidates.get(name)
            if seen == _STRING_ONLY:
                continue
            candidates[name] = matching_types(text, TYPE_PRIORITY if seen is None else seen)
    return candidates


def _pool_types(per_file: list[Candidates]) -> dict[str, str]:
    """Type every column against the values of all files at once (loose mode)."""
    pooled: Candidates = {}
    for candidates in per_file:
        for name, types in candidates.items():
            pooled[name] = pooled[name] & types if name in pooled else set(types)
    return {name: best_type(types) for name, types in pooled.items()}


def _agreed_types(per_file: list[Candidates]) -> dict[str, str]:
    """Type each file separately and fall back to string on disagreement (strict mode)."""
    agreed: dict[str, str] = {}
    for candidates in per_file:
        for name, types in candidates.items():
            chosen = best_type(types)
            if agreed.setdefault(name, chosen) != chosen:
                agreed[name] = "string"
    return agreed
