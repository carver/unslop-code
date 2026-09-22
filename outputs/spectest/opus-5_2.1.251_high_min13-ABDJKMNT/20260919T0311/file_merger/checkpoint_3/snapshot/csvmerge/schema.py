"""The resolved output schema, and loading an explicit one from JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .casting import TYPES
from .errors import EXIT_SCHEMA, MergeError


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]


def load_schema(source: str) -> Schema:
    """Load an explicit schema from an inline JSON document or a path to one."""
    text = source if source.lstrip().startswith("{") else Path(source).read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MergeError(f"invalid schema JSON: {exc}", EXIT_SCHEMA) from None

    entries = document.get("columns") if isinstance(document, dict) else None
    if not entries:
        raise MergeError("schema document must contain a non-empty 'columns' list", EXIT_SCHEMA)

    columns = []
    for entry in entries:
        name, type_name = entry["name"], entry["type"]
        if type_name not in TYPES:
            raise MergeError(f"unknown type {type_name!r} for column {name!r}", EXIT_SCHEMA)
        columns.append(Column(name, type_name))
    return Schema(tuple(columns))
