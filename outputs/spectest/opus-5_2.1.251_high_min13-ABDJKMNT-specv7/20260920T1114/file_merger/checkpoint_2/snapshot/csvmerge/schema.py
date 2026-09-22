"""The resolved output schema: ordered columns with a declared type each."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.types import TYPES


@dataclass(frozen=True)
class Column:
    """One output column and the type every cell in it is cast to."""

    name: str
    type: str


@dataclass(frozen=True)
class Schema:
    """The output column order, shared by the header, every row and the sort keys."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def positions_of(self, names: list[str]) -> list[int]:
        """Indexes of `names` in this schema; unknown names are an error."""
        known = self.names
        unknown = [name for name in names if name not in known]
        if unknown:
            raise MergeError(
            f"key column(s) not in resolved schema: {', '.join(unknown)}", EXIT_SCHEMA
        )
        return [known.index(name) for name in names]


def load_schema(path: str) -> Schema:
    """Read the schema JSON file given with --schema."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MergeError(f"cannot read schema {path}: {error}", EXIT_SCHEMA) from error
    if not isinstance(document, dict) or not isinstance(document.get("columns"), list):
        raise MergeError(
            f"schema {path} must be an object with a 'columns' list", EXIT_SCHEMA
        )
    return Schema(tuple(_column(entry) for entry in document["columns"]))


def _column(entry: object) -> Column:
    """Validate one entry of the schema's "columns" list."""
    if not isinstance(entry, dict) or "name" not in entry or "type" not in entry:
        raise MergeError(
            f"schema column must have 'name' and 'type': {entry!r}", EXIT_SCHEMA
        )
    if entry["type"] not in TYPES:
        raise MergeError(
            f"unknown type {entry['type']!r} for column {entry['name']!r}; "
            f"valid types are {', '.join(sorted(TYPES))}",
            EXIT_SCHEMA,
        )
    return Column(str(entry["name"]), entry["type"])
