"""Resolving the output schema, either from a JSON document or by inference."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .casting import TYPE_PRIORITY, TYPES, has_time_part, matching_types
from .csvio import open_table
from .errors import MergeError


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
        raise MergeError(f"invalid schema JSON: {exc}") from None

    entries = document.get("columns") if isinstance(document, dict) else None
    if not entries:
        raise MergeError("schema document must contain a non-empty 'columns' list")

    columns = []
    for entry in entries:
        name, type_name = entry["name"], entry["type"]
        if type_name not in TYPES:
            raise MergeError(f"unknown type {type_name!r} for column {name!r}")
        columns.append(Column(name, type_name))
    return Schema(tuple(columns))


@dataclass
class ColumnEvidence:
    """Which types have parsed every value observed for one column, so far."""

    candidates: set[str] = field(default_factory=lambda: set(TYPE_PRIORITY))
    saw_time_part: bool = False
    saw_value: bool = False

    def observe(self, text: str) -> None:
        self.candidates &= matching_types(text)
        self.saw_time_part = self.saw_time_part or has_time_part(text)
        self.saw_value = True

    def combine(self, other: "ColumnEvidence") -> "ColumnEvidence":
        """Evidence from two sources pooled into one."""
        return ColumnEvidence(
            self.candidates & other.candidates,
            self.saw_time_part or other.saw_time_part,
            self.saw_value or other.saw_value,
        )

    def resolve(self) -> str:
        """The highest-priority type that parses every observed value."""
        if not self.saw_value:
            return "string"
        for name in TYPE_PRIORITY[:-1]:  # `string` is the guaranteed fallback
            # A date-only column stays `date` even though it also parses as a
            # timestamp, which would otherwise make `date` unreachable.
            if name in self.candidates and (name != "timestamp" or self.saw_time_part):
                return name
        return "string"


def infer_schema(
    paths: Sequence[str],
    dialect: dict,
    mode: str,
    is_null: Callable[[str], bool],
) -> Schema:
    """Infer the schema from the union of the input headers, ordered lexicographically.

    `strict` types each file on its own and falls back to `string` when files
    disagree; `loose` pools values across files and ignores nulls.
    """
    names: set[str] = set()
    per_file: list[dict[str, ColumnEvidence]] = []
    for path in paths:
        evidence: dict[str, ColumnEvidence] = {}
        with open_table(path, dialect) as (header, rows):
            names.update(header)
            for row in rows:
                for name, text in zip(header, row):
                    if mode == "loose" and is_null(text):
                        continue
                    evidence.setdefault(name, ColumnEvidence()).observe(text)
        per_file.append(evidence)

    return Schema(
        tuple(
            Column(name, _resolve_across_files([f[name] for f in per_file if name in f], mode))
            for name in sorted(names)
        )
    )


def _resolve_across_files(evidences: Iterable[ColumnEvidence], mode: str) -> str:
    """Combine one column's per-file evidence into a single type."""
    evidences = list(evidences)
    if not evidences:
        return "string"
    if mode == "loose":
        return reduce(ColumnEvidence.combine, evidences).resolve()

    types = {evidence.resolve() for evidence in evidences}
    return types.pop() if len(types) == 1 else "string"
