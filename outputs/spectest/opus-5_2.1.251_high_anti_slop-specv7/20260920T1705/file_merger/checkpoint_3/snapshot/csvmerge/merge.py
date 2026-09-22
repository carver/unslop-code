"""Orchestration: resolve the schema, cast every input row, sort, write."""

from __future__ import annotations

import itertools
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Sequence

from .coltypes import CastError, cast_value, format_value
from .csvio import open_output, write_rows
from .errors import MergeError
from .formats import Source
from .partitioning import segments
from .readers import rows
from .schema import InferMode, Schema, SchemaStrategy, infer_schema, load_schema
from .sharding import ShardLimits, write_shards
from .sorting import Record, budget_from_limit, external_sort, make_sort_key, rank_value


class TypeErrorPolicy(str, Enum):
    """What to do with a cell that does not fit its column's type."""

    COERCE_NULL = "coerce-null"
    FAIL = "fail"
    KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class MergeConfig:
    """Everything one invocation needs, as parsed from the command line."""

    sources: Sequence[Source]
    output: str
    keys: Sequence[str]
    descending: bool = False
    schema_path: str | None = None
    infer_mode: InferMode = InferMode.STRICT
    schema_strategy: SchemaStrategy = SchemaStrategy.AUTHORITATIVE
    on_type_error: TypeErrorPolicy = TypeErrorPolicy.COERCE_NULL
    memory_limit_mb: int = 256
    temp_dir: str | None = None
    null_literal: str = ""
    partition_by: Sequence[str] = ()
    max_rows_per_file: int | None = None
    max_bytes_per_file: int | None = None

    @property
    def writes_directory(self) -> bool:
        """Whether ``output`` names a directory of part files rather than a file."""
        return bool(self.partition_by or self.max_rows_per_file or self.max_bytes_per_file)

    @property
    def limits(self) -> ShardLimits:
        """The per-part-file size limits, as the shard writer wants them."""
        return ShardLimits(self.max_rows_per_file, self.max_bytes_per_file)


def merge(config: MergeConfig) -> None:
    """Merge every input into sorted CSV at the configured destination."""
    schema = resolve_schema(config)
    key_positions = schema.positions(config.keys)
    partition_positions = schema.positions(config.partition_by, role="partition")
    with tempfile.TemporaryDirectory(dir=config.temp_dir, prefix="merge-files-") as workdir:
        ordered = external_sort(
            records=_records(config, schema, key_positions, partition_positions),
            key=make_sort_key(config.descending),
            workdir=Path(workdir),
            budget_bytes=budget_from_limit(config.memory_limit_mb),
        )
        if config.writes_directory:
            write_shards(
                config.output, schema.names, ordered, config.null_literal, config.limits
            )
            return
        with open_output(config.output) as handle:
            write_rows(
                handle,
                schema.names,
                (record.cells for record in ordered),
                config.null_literal,
            )


def resolve_schema(config: MergeConfig) -> Schema:
    """Load the declared schema, or infer one from the inputs."""
    if config.schema_path is not None:
        return load_schema(config.schema_path)
    return infer_schema(config.sources, config.infer_mode, config.schema_strategy)


def _records(
    config: MergeConfig,
    schema: Schema,
    key_positions: Sequence[int],
    partition_positions: Sequence[int],
) -> Iterator[Record]:
    """Cast every input row, place it in its partition and number it.

    The numbering is the row's order of appearance across the inputs, which is
    what makes the sort stable, and the partition segments are derived from the
    already-cast cells so they match what the CSV prints.
    """
    sequence = itertools.count()
    for source in config.sources:
        for row in rows(source):
            values = _cast_row(
                row.values, schema, config.on_type_error, f"{source.path}:{row.position}"
            )
            cells = tuple(None if value is None else format_value(value) for value in values)
            yield Record(
                partition=segments(
                    config.partition_by,
                    [cells[position] for position in partition_positions],
                ),
                ranked=tuple(rank_value(values[position]) for position in key_positions),
                sequence=next(sequence),
                cells=cells,
            )


def _cast_row(
    row: dict[str, Any],
    schema: Schema,
    policy: TypeErrorPolicy,
    location: str,
) -> list[Any]:
    """Cast one raw row into schema order, applying the type-error policy.

    Columns the file does not provide, cells holding the null literal and typed
    nulls all stay ``None`` and are written out as the null literal.
    """
    values: list[Any] = []
    for column in schema.columns:
        cell = row.get(column.name)
        if cell is None:
            values.append(None)
            continue
        try:
            values.append(cast_value(cell, column.type))
        except CastError as error:
            if policy is TypeErrorPolicy.FAIL:
                raise MergeError(
                    f"{location}: column {column.name!r} expects {column.type.value}: {error}"
                ) from error
            values.append(format_value(cell) if policy is TypeErrorPolicy.KEEP_STRING else None)
    return values
