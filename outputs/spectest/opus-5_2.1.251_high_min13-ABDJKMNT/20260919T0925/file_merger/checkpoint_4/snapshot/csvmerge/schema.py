"""The resolved output schema, and loading one from an explicit JSON document."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import SchemaError
from .typespec import parse_type

STRICT = "strict"
LOOSE = "loose"
INFER_MODES = (STRICT, LOOSE)


@dataclass(frozen=True)
class Column:
    """One output column and the type — primitive, nested or `json` — it holds."""

    name: str
    type: object


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self):
        return [column.name for column in self.columns]


def load_schema(source, aliases):
    """Load a schema from a JSON file path, or from inline JSON (AMBIGUITIES T12)."""
    text = source if source.lstrip().startswith("{") else _read_schema_file(source)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SchemaError(f"schema is not valid JSON: {error}") from error

    columns = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(columns, list) or not columns:
        raise SchemaError("schema must contain a non-empty 'columns' list")
    return Schema(tuple(_build_column(entry, aliases) for entry in columns))


def _read_schema_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SchemaError(f"cannot read schema {path}: {error}") from error


def _build_column(entry, aliases):
    if not isinstance(entry, dict) or not entry.get("name"):
        raise SchemaError(f"invalid schema column {entry!r}: it must have a name")
    return Column(entry["name"], parse_type(entry.get("type"), aliases))
