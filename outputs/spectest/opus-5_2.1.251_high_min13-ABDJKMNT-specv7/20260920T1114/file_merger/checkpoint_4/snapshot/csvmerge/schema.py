"""The resolved output schema: ordered columns with a declared type each."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from csvmerge.aliases import AliasTable
from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.typespec import DataType, parse_type


@dataclass(frozen=True)
class Column:
    """One output column and the type every value in it is cast to."""

    name: str
    type: DataType


@dataclass(frozen=True)
class Schema:
    """The output column order, shared by the header, every row and the keys."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def type_of(self, name: str) -> DataType | None:
        """The declared type of one column, or None when there is no such column."""
        return next(
            (column.type for column in self.columns if column.name == name), None
        )


def load_schema(path: str, aliases: AliasTable) -> Schema:
    """Read the schema JSON file given with --schema."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MergeError(f"cannot read schema {path}: {error}", EXIT_SCHEMA) from error
    if not isinstance(document, dict) or not isinstance(document.get("columns"), list):
        raise MergeError(
            f"schema {path} must be an object with a 'columns' list", EXIT_SCHEMA
        )
    return Schema(tuple(_column(entry, aliases) for entry in document["columns"]))


def _column(entry: object, aliases: AliasTable) -> Column:
    """Validate one entry of the schema's "columns" list."""
    if not isinstance(entry, dict) or "name" not in entry or "type" not in entry:
        raise MergeError(
            f"schema column must have 'name' and 'type': {entry!r}", EXIT_SCHEMA
        )
    name = str(entry["name"])
    return Column(name, parse_type(entry["type"], aliases, f"column {name!r}"))
