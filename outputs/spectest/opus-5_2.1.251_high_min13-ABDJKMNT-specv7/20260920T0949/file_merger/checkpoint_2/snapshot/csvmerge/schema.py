"""The resolved output schema and the loader for ``--schema`` files."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .casting import TYPES, TypeSpec
from .errors import KeyColumnError, ToolError


@dataclass(frozen=True)
class Column:
    """One output column: its header name and the type its cells are cast to."""

    name: str
    spec: TypeSpec


@dataclass(frozen=True)
class Schema:
    """The resolved output schema, in output column order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def index_of(self, name: str) -> int:
        """Position of ``name`` in the output, or raise if it is unknown."""
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        raise KeyColumnError(f"key column {name!r} is not present in the resolved schema")


def schema_from_types(pairs) -> Schema:
    """Build a schema from ``(name, type name)`` pairs already in output order."""
    return Schema(tuple(Column(name, TYPES[type_name]) for name, type_name in pairs))


def load_schema(path: str) -> Schema:
    """Read a schema JSON file describing the exact output columns and order."""
    with open(path, encoding="utf-8") as handle:
        try:
            document = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ToolError(f"{path}: invalid JSON ({exc})") from None

    columns = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(columns, list) or not columns:
        raise ToolError(f"{path}: expected a non-empty 'columns' list")

    return schema_from_types(_column_pair(path, entry) for entry in columns)


def _column_pair(path: str, entry) -> tuple[str, str]:
    """Validate one entry of the schema file's ``columns`` list."""
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise ToolError(f"{path}: every column needs a string 'name'")
    type_name = entry.get("type")
    if type_name not in TYPES:
        raise ToolError(f"{path}: column {entry['name']!r} has unsupported type {type_name!r}")
    return entry["name"], type_name
