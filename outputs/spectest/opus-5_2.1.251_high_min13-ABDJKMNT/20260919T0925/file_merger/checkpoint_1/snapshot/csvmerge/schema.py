"""Resolving the output schema: explicit JSON schemas and inference from inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .coltypes import STRING, VALID_TYPES, candidate_types, resolve_priority
from .errors import MergeError

STRICT = "strict"
LOOSE = "loose"


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


class SchemaInferrer:
    """Accumulates observed cells and resolves an inferred schema.

    ``strict`` resolves one type per input file and demands that every file agree,
    falling back to ``string`` otherwise; ``loose`` intersects the candidate types of
    every observed value across all files. Nulls never constrain either mode.
    """

    def __init__(self, mode):
        self._strict = mode == STRICT
        self._names = set()
        self._file_candidates = {}
        self._per_file_types = {}

    def add_header(self, names):
        self._names.update(names)

    def observe(self, name, text):
        """Record one non-null cell for `name`."""
        candidates = candidate_types(text)
        seen = self._file_candidates.get(name)
        self._file_candidates[name] = candidates if seen is None else seen & candidates

    def end_file(self):
        """Close the current file's scope; only ``strict`` narrows per file."""
        if not self._strict:
            return
        for name, candidates in self._file_candidates.items():
            self._per_file_types.setdefault(name, set()).add(resolve_priority(candidates))
        self._file_candidates = {}

    def resolve(self):
        """Return the inferred schema, ordered lexicographically by column name."""
        return Schema(tuple(Column(name, self._type_of(name)) for name in sorted(self._names)))

    def _type_of(self, name):
        if not self._strict:
            return resolve_priority(self._file_candidates.get(name, set()))
        opinions = self._per_file_types.get(name, set())
        return next(iter(opinions)) if len(opinions) == 1 else STRING
