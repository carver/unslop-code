"""Resolving the output schema, either from a JSON file or by inference."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from .errors import SchemaError
from .sources import Candidates, InputSpec, ReadOptions, scan_types
from .types import TYPE_PRIORITY, ColumnType


class InferMode(str, Enum):
    """How aggressively to infer types when no schema file is supplied."""

    STRICT = "strict"
    LOOSE = "loose"


class SchemaStrategy(str, Enum):
    """How to settle a column whose inputs disagree about its type."""

    AUTHORITATIVE = "authoritative"
    CONSENSUS = "consensus"
    UNION = "union"


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


@dataclass(frozen=True)
class Schema:
    """The resolved output columns, in output order."""

    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [column.name for column in self.columns]

    def index_of(self, name: str) -> int:
        """Return the output position of ``name``, or raise if it is absent."""
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        raise SchemaError(f"key column {name!r} is not present in the resolved schema")


def load_schema(path: str) -> Schema:
    """Load an explicit schema: ``{"columns": [{"name": ..., "type": ...}, ...]}``."""
    with open(path, encoding="utf-8") as stream:
        try:
            document = json.load(stream)
        except json.JSONDecodeError as error:
            raise SchemaError(f"{path}: invalid JSON ({error})") from error
    entries = document.get("columns")
    if not isinstance(entries, list) or not entries:
        raise SchemaError(f"{path}: schema must contain a non-empty 'columns' list")
    return Schema(tuple(_parse_column(entry, path) for entry in entries))


def infer_schema(
    specs: Sequence[InputSpec], options: ReadOptions, mode: InferMode, strategy: SchemaStrategy
) -> Schema:
    """Infer a schema from the union of every input's columns, ordered lexicographically.

    ``mode`` decides what each file on its own observes — ``strict`` counts a
    null as an observation only ``string`` satisfies, ``loose`` ignores nulls —
    and ``strategy`` decides how files that end up disagreeing are reconciled.
    """
    scans = [(spec.precedence, scan_types(spec, options, mode is InferMode.LOOSE)) for spec in specs]
    names = sorted({name for _precedence, candidates in scans for name in candidates})
    return Schema(tuple(Column(name, _resolve(name, scans, mode, strategy)) for name in names))


#: One file's view of one column: how much its format's types are trusted, and
#: which types its values allow (``None`` when it observed no value at all).
_Observation = tuple[int, set[ColumnType] | None]


def _resolve(
    name: str, scans: Iterable[tuple[int, Candidates]], mode: InferMode, strategy: SchemaStrategy
) -> ColumnType:
    observed = [(precedence, seen[name]) for precedence, seen in scans if name in seen]
    return _STRATEGIES[strategy](observed, mode)


def _authoritative(observed: Sequence[_Observation], mode: InferMode) -> ColumnType:
    """Let the most strongly typed sources present decide, and ignore the rest."""
    trusted = max(precedence for precedence, _candidates in observed)
    return _MODES[mode]([candidates for precedence, candidates in observed if precedence == trusted])


def _consensus(observed: Sequence[_Observation], mode: InferMode) -> ColumnType:
    """Take the type most files resolve to on their own; a tie falls back to the union."""
    votes = Counter(
        _highest_priority(candidates) for _precedence, candidates in observed if candidates is not None
    )
    majority = max(votes.values(), default=0)
    leaders = [column_type for column_type, count in votes.items() if count == majority]
    if len(leaders) == 1:
        return leaders[0]
    return _union(observed, mode)


def _union(observed: Sequence[_Observation], _mode: InferMode) -> ColumnType:
    """Take the simplest type every observed value still fits into."""
    return _resolve_loose(candidates for _precedence, candidates in observed)


def _resolve_loose(per_file: Iterable[set[ColumnType] | None]) -> ColumnType:
    observed = [candidates for candidates in per_file if candidates is not None]
    if not observed:
        return ColumnType.STRING
    return _highest_priority(set.intersection(*observed))


def _resolve_strict(per_file: Iterable[set[ColumnType] | None]) -> ColumnType:
    types = {_highest_priority(candidates) for candidates in per_file if candidates is not None}
    if len(types) == 1:
        return types.pop()
    return ColumnType.STRING


_STRATEGIES = {
    SchemaStrategy.AUTHORITATIVE: _authoritative,
    SchemaStrategy.CONSENSUS: _consensus,
    SchemaStrategy.UNION: _union,
}

#: Within one set of files, ``strict`` demands they agree outright while
#: ``loose`` merges them onto the type they all still fit.
_MODES = {InferMode.STRICT: _resolve_strict, InferMode.LOOSE: _resolve_loose}


def _parse_column(entry: dict, path: str) -> Column:
    try:
        return Column(entry["name"], ColumnType(entry["type"]))
    except (KeyError, TypeError) as error:
        raise SchemaError(f"{path}: every schema column needs a 'name' and a 'type'") from error
    except ValueError as error:
        supported = ", ".join(column_type.value for column_type in ColumnType)
        raise SchemaError(f"{path}: unknown type {entry['type']!r} (expected one of: {supported})") from error


def _highest_priority(candidates: set[ColumnType]) -> ColumnType:
    return next((column_type for column_type in TYPE_PRIORITY if column_type in candidates), ColumnType.STRING)
