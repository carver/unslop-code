"""Orchestration: resolve the schema, cast every input row, sort, write."""

from __future__ import annotations

import itertools
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator, Sequence

from .coltypes import CastError, cast, format_value
from .csvio import InputDialect, open_output, read_rows, write_rows
from .schema import InferMode, Schema, load_schema, infer_schema
from .sorting import Record, budget_from_limit, external_sort, make_sort_key, rank_value


class MergeError(RuntimeError):
    """Raised for user-facing failures that should abort the run."""


class TypeErrorPolicy(str, Enum):
    """What to do with a cell that does not fit its column's type."""

    COERCE_NULL = "coerce-null"
    FAIL = "fail"
    KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class MergeConfig:
    """Everything one invocation needs, as parsed from the command line."""

    sources: Sequence[str]
    output: str
    keys: Sequence[str]
    descending: bool = False
    schema_path: str | None = None
    infer_mode: InferMode = InferMode.STRICT
    on_type_error: TypeErrorPolicy = TypeErrorPolicy.COERCE_NULL
    memory_limit_mb: int = 256
    temp_dir: str | None = None
    dialect: InputDialect = InputDialect()


def merge(config: MergeConfig) -> None:
    """Merge every input into one sorted CSV at the configured destination."""
    schema = resolve_schema(config)
    key_positions = schema.positions(config.keys)
    with tempfile.TemporaryDirectory(dir=config.temp_dir, prefix="merge-files-") as workdir:
        ordered = external_sort(
            records=_records(config, schema, key_positions),
            key=make_sort_key(config.descending),
            workdir=Path(workdir),
            budget_bytes=budget_from_limit(config.memory_limit_mb),
        )
        with open_output(config.output) as handle:
            write_rows(
                handle,
                schema.names,
                (record.cells for record in ordered),
                config.dialect.null_literal,
            )


def resolve_schema(config: MergeConfig) -> Schema:
    """Load the declared schema, or infer one from the inputs."""
    if config.schema_path is not None:
        return load_schema(config.schema_path)
    return infer_schema(config.sources, config.infer_mode, config.dialect)


def _records(
    config: MergeConfig, schema: Schema, key_positions: Sequence[int]
) -> Iterator[Record]:
    """Cast every input row and number it by order of appearance."""
    sequence = itertools.count()
    for source in config.sources:
        for line, row in enumerate(read_rows(source, config.dialect), start=2):
            values = _cast_row(row, schema, config.on_type_error, f"{source}:{line}")
            yield Record(
                ranked=tuple(rank_value(values[position]) for position in key_positions),
                sequence=next(sequence),
                cells=tuple(None if value is None else format_value(value) for value in values),
            )


def _cast_row(
    row: dict[str, str | None],
    schema: Schema,
    policy: TypeErrorPolicy,
    location: str,
) -> list[object]:
    """Cast one raw row into schema order, applying the type-error policy.

    Columns the file does not provide, and cells holding the null literal, stay
    ``None`` and are written out as the null literal.
    """
    values: list[object] = []
    for column in schema.columns:
        text = row.get(column.name)
        if text is None:
            values.append(None)
            continue
        try:
            values.append(cast(text, column.type))
        except CastError as error:
            if policy is TypeErrorPolicy.FAIL:
                raise MergeError(
                    f"{location}: column {column.name!r} expects {column.type.value}: {error}"
                ) from error
            values.append(text if policy is TypeErrorPolicy.KEEP_STRING else None)
    return values
