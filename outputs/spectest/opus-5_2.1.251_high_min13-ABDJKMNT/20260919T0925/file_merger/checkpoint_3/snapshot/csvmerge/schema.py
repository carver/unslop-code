"""The resolved output schema, and loading one from an explicit JSON document."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .coltypes import VALID_TYPES
from .errors import MergeError

STRICT = "strict"
LOOSE = "loose"
INFER_MODES = (STRICT, LOOSE)


class SchemaError(MergeError):
    """Raised when a schema document is unusable."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self):
        return [column.name for column in self.columns]


def load_schema(source):
    """Load a schema from a JSON file path, or from inline JSON (AMBIGUITIES T12)."""
    text = source if source.lstrip().startswith("{") else _read_schema_file(source)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SchemaError(f"schema is not valid JSON: {error}") from error

    columns = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(columns, list) or not columns:
        raise SchemaError("schema must contain a non-empty 'columns' list")
    return Schema(tuple(_build_column(entry) for entry in columns))


def _read_schema_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SchemaError(f"cannot read schema {path}: {error}") from error


def _build_column(entry):
    name, column_type = entry.get("name"), entry.get("type")
    if not name or column_type not in VALID_TYPES:
        raise SchemaError(f"invalid schema column {entry!r}: unknown type {column_type!r}")
    return Column(name, column_type)
