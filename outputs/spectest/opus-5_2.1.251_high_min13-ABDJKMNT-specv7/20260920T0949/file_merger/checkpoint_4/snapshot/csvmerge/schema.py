"""The resolved output schema and the loader for ``--schema`` files."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .aliases import Aliases
from .casting import TYPES
from .datatypes import DataType, Primitive, parse_type
from .errors import KeyColumnError, ToolError


@dataclass(frozen=True)
class Column:
    """One output column: its header name and the type its cells are cast to."""

    name: str
    type: DataType


@dataclass(frozen=True)
class Schema:
    """The resolved output schema, in output column order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def index_of(self, name: str, role: str = "key") -> int:
        """Position of ``name`` in the output, or raise if it is unknown.

        ``role`` names the flag the column came from, so that a missing
        ``--partition-by`` column reports itself as one.
        """
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        raise KeyColumnError(f'ERR 3 {role} column "{name}" is not present in the resolved schema')


def schema_from_types(pairs) -> Schema:
    """Build a schema from ``(name, primitive type name)`` pairs, in output order."""
    return Schema(tuple(Column(name, Primitive(TYPES[type_name])) for name, type_name in pairs))


def load_schema(path: str, aliases: Aliases) -> Schema:
    """Read a schema JSON file describing the exact output columns and order."""
    with open(path, encoding="utf-8") as handle:
        try:
            document = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ToolError(f"{path}: invalid JSON ({exc})") from None

    columns = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(columns, list) or not columns:
        raise ToolError(f"{path}: expected a non-empty 'columns' list")

    return Schema(tuple(_column(path, entry, aliases) for entry in columns))


def _column(path: str, entry, aliases: Aliases) -> Column:
    """Validate one entry of the schema file's ``columns`` list."""
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise ToolError(f"{path}: every column needs a string 'name'")
    name = entry["name"]
    return Column(name, parse_type(entry.get("type"), aliases, f"{path}: column {name!r}"))
