"""Orchestration: resolve the schema, cast every input row, sort, write."""

from __future__ import annotations

import itertools
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .aliases import load_aliases
from .casting import CastContext, TypeErrorPolicy, cast_row, render_cell
from .csvio import open_output, write_rows
from .formats import Source
from .partitioning import segments
from .paths import ResolvedPath, resolve_paths
from .readers import rows
from .schema import InferMode, Schema, SchemaStrategy, infer_schema, load_schema
from .sharding import ShardLimits, write_shards
from .sorting import Record, budget_from_limit, external_sort, make_sort_key, rank_value


@dataclass(frozen=True)
class MergeConfig:
    """Everything one invocation needs, as parsed from the command line."""

    sources: Sequence[Source]
    output: str
    keys: Sequence[str]
    descending: bool = False
    schema_path: str | None = None
    alias_path: str | None = None
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
    keys = resolve_paths(config.keys, schema)
    partitions = resolve_paths(config.partition_by, schema, role="partition")
    with tempfile.TemporaryDirectory(dir=config.temp_dir, prefix="merge-files-") as workdir:
        ordered = external_sort(
            records=_records(config, schema, keys, partitions),
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
    aliases = load_aliases(config.alias_path)
    if config.schema_path is not None:
        return load_schema(config.schema_path, aliases)
    return infer_schema(config.sources, config.infer_mode, config.schema_strategy)


def _records(
    config: MergeConfig,
    schema: Schema,
    keys: Sequence[ResolvedPath],
    partitions: Sequence[ResolvedPath],
) -> Iterator[Record]:
    """Cast every input row, place it in its partition and number it.

    The numbering is the row's order of appearance across the inputs, which is
    what makes the sort stable.  Key and partition values are read out of the
    cast row, so a field path sees the same value the CSV goes on to print.
    """
    sequence = itertools.count()
    names = [path.text for path in partitions]
    for source in config.sources:
        for row in rows(source):
            context = CastContext(
                config.on_type_error, source.path, row.position, source.text_cells
            )
            values = cast_row(row.values, schema.columns, context)
            yield Record(
                partition=segments(names, [path.read(values) for path in partitions]),
                ranked=tuple(rank_value(path.read(values)) for path in keys),
                sequence=next(sequence),
                cells=tuple(
                    render_cell(value, column.type)
                    for value, column in zip(values, schema.columns)
                ),
            )
