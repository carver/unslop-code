"""Resolution of the output schema: either loaded from JSON or inferred.

Inference observes every input once — Parquet through its declared schema, the
other formats by scanning their values — and then reconciles the per-file
observations of each column with the chosen ``--schema-strategy``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from .coltypes import DECLARED_CANDIDATES, ColumnType, candidates, narrowest
from .errors import KeyColumnError, SchemaError
from .formats import Source
from .readers import declared_types, header_names, rows


class InferMode(str, Enum):
    """How inference treats nulls and disagreements between files."""

    STRICT = "strict"
    LOOSE = "loose"


class SchemaStrategy(str, Enum):
    """How a column's type is chosen when the inputs disagree about it."""

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
    def names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def positions(self, names: Iterable[str], role: str = "key") -> list[int]:
        """Indexes of ``names`` within the schema, rejecting unknown columns."""
        order = self.names
        unknown = [name for name in names if name not in order]
        if unknown:
            raise KeyColumnError(
                f"{role} column(s) {', '.join(unknown)} are not in the resolved schema: "
                f"{', '.join(order)}"
            )
        return [order.index(name) for name in names]


@dataclass(frozen=True)
class Observation:
    """What one input says about its columns.

    ``candidates`` holds, per column the file carries values for, the types
    every one of those values fits; ``names`` also covers columns the file
    declares but never fills.  ``rank`` is the format's precedence, which only
    the ``authoritative`` strategy looks at.
    """

    rank: int
    names: frozenset[str]
    candidates: dict[str, frozenset[ColumnType]]


def load_schema(path: str) -> Schema:
    """Read an explicit schema definition from a JSON file."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as error:
        raise SchemaError(f"{path}: invalid JSON: {error}") from error
    definitions = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(definitions, list) or not definitions:
        raise SchemaError(f"{path}: expected a non-empty 'columns' array")
    columns = [_column_from_json(path, definition) for definition in definitions]
    names = [column.name for column in columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SchemaError(f"{path}: duplicate column(s) {', '.join(duplicates)}")
    return Schema(tuple(columns))


def _column_from_json(path: str, definition: Any) -> Column:
    if not isinstance(definition, dict) or "name" not in definition or "type" not in definition:
        raise SchemaError(f"{path}: every column needs a 'name' and a 'type', got {definition!r}")
    try:
        return Column(str(definition["name"]), ColumnType(definition["type"]))
    except ValueError as error:
        raise SchemaError(
            f"{path}: unknown type {definition['type']!r}; valid types are "
            f"{', '.join(member.value for member in ColumnType)}"
        ) from error


def infer_schema(
    sources: Sequence[Source], mode: InferMode, strategy: SchemaStrategy
) -> Schema:
    """Infer the union of the inputs' columns, ordered lexicographically."""
    observations = [_observe(source, mode) for source in sources]
    names = sorted({name for observation in observations for name in observation.names})
    return Schema(
        tuple(Column(name, _resolve(name, observations, mode, strategy)) for name in names)
    )


def _observe(source: Source, mode: InferMode) -> Observation:
    """Collect one input's columns and the types each of them supports."""
    declared = declared_types(source)
    if declared is not None:
        return Observation(
            source.rank,
            frozenset(declared),
            {name: DECLARED_CANDIDATES[column_type] for name, column_type in declared.items()},
        )
    scanned = _scan(source, mode)
    return Observation(source.rank, frozenset(header_names(source)) | frozenset(scanned), scanned)


def _scan(source: Source, mode: InferMode) -> dict[str, frozenset[ColumnType]]:
    """Intersect the candidate types of every value of every column in one file.

    ``loose`` skips nulls, so they cannot widen a column.  ``strict`` treats a
    null as a value that only ``string`` accepts.
    """
    constraints: dict[str, frozenset[ColumnType]] = {}
    for row in rows(source):
        for name, value in row.values.items():
            if value is None:
                if mode is InferMode.LOOSE:
                    continue
                supported = frozenset({ColumnType.STRING})
            else:
                supported = candidates(value)
            previous = constraints.get(name)
            constraints[name] = supported if previous is None else previous & supported
    return constraints


def _agree(per_file: Sequence[frozenset[ColumnType]], mode: InferMode) -> ColumnType:
    """Combine the candidate sets of files that rank equally.

    ``loose`` keeps the most specific type that fits every value anywhere;
    ``strict`` resolves each file on its own and falls back to ``string`` as
    soon as two files land on different types.
    """
    if mode is InferMode.LOOSE:
        return narrowest(frozenset.intersection(*per_file))
    per_file_types = {narrowest(supported) for supported in per_file}
    return per_file_types.pop() if len(per_file_types) == 1 else ColumnType.STRING


def _authoritative(
    observed: Sequence[tuple[int, frozenset[ColumnType]]], mode: InferMode
) -> ColumnType:
    """Let the highest-precedence format that carries the column decide."""
    best = min(rank for rank, _ in observed)
    return _agree([supported for rank, supported in observed if rank == best], mode)


def _consensus(
    observed: Sequence[tuple[int, frozenset[ColumnType]]], mode: InferMode
) -> ColumnType:
    """Take the most specific type a majority of the files can represent."""
    support = Counter(column_type for _, supported in observed for column_type in supported)
    majority = len(observed) // 2 + 1
    return narrowest(
        column_type for column_type, count in support.items() if count >= majority
    )


def _union(
    observed: Sequence[tuple[int, frozenset[ColumnType]]], mode: InferMode
) -> ColumnType:
    """Take the simplest type that can hold every value of every file."""
    return narrowest(frozenset.intersection(*(supported for _, supported in observed)))


#: The strategies share one signature — the per-file observations of a column
#: and the inference mode — so ``_resolve`` can pick one by name.
_STRATEGIES: dict[
    SchemaStrategy, Callable[[Sequence[tuple[int, frozenset[ColumnType]]], InferMode], ColumnType]
] = {
    SchemaStrategy.AUTHORITATIVE: _authoritative,
    SchemaStrategy.CONSENSUS: _consensus,
    SchemaStrategy.UNION: _union,
}


def _resolve(
    name: str,
    observations: Sequence[Observation],
    mode: InferMode,
    strategy: SchemaStrategy,
) -> ColumnType:
    """Settle one column's type from the files that hold values for it."""
    observed = [
        (observation.rank, observation.candidates[name])
        for observation in observations
        if name in observation.candidates
    ]
    if not observed:
        return ColumnType.STRING
    return _STRATEGIES[strategy](observed, mode)
