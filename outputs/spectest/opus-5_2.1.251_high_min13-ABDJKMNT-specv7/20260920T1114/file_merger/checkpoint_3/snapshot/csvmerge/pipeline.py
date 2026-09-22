"""Wiring: resolve the inputs and the schema, cast every record, sort, write."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from csvmerge.cli import Options
from csvmerge.detect import resolve
from csvmerge.dialect import CsvDialect
from csvmerge.inference import infer_schema
from csvmerge.partition import segments
from csvmerge.parts import Limits, write_parts
from csvmerge.rows import convert_row, is_null
from csvmerge.schema import Schema, load_schema
from csvmerge.sorter import ExternalSorter
from csvmerge.sources import Source
from csvmerge.writer import staged_directory, write_output

BYTES_PER_MB = 1024 * 1024


def run(options: Options) -> None:
    """Execute one merge; raises MergeError for anything the user must fix."""
    dialect = CsvDialect(options.quotechar, options.escapechar, options.null_literal)
    sources = _build_sources(options, dialect)
    schema = (
        load_schema(options.schema)
        if options.schema
        else infer_schema(sources, options.infer, options.schema_strategy)
    )
    layout = _Layout.of(options, schema, dialect)
    with TemporaryDirectory(dir=options.temp_dir, prefix="csvmerge-") as workspace:
        sorter = ExternalSorter(
            Path(workspace), options.memory_limit_mb * BYTES_PER_MB, options.descending
        )
        for source in sources:
            with source.read() as (_, records):
                for record in records:
                    sorter.add(*layout.row(record))
        _emit(options, dialect, schema, layout, sorter)


@dataclass(frozen=True)
class _Layout:
    """Turns a record into the sort key it is filed under and the cells it prints.

    The key starts with the row's partition segments so that the sorted stream
    arrives grouped by partition, each group in `--key` order.
    """

    schema: Schema
    dialect: CsvDialect
    policy: str
    key_positions: list[int]
    partition_names: list[str]
    partition_positions: list[int]

    @classmethod
    def of(cls, options: Options, schema: Schema, dialect: CsvDialect) -> "_Layout":
        """Resolve the key and partition columns against the output schema."""
        return cls(
            schema,
            dialect,
            options.on_type_error,
            schema.positions_of(options.keys),
            options.partition_by,
            schema.positions_of(options.partition_by, "partition"),
        )

    def row(self, record: dict[str, object]) -> tuple[list, list[str]]:
        """One record as its sort key and its output cells."""
        cells, keys = convert_row(record, self.schema, self.dialect, self.policy)
        values = [
            None if is_null(keys[position]) else cells[position]
            for position in self.partition_positions
        ]
        key = [
            *segments(self.partition_names, values),
            *(keys[position] for position in self.key_positions),
        ]
        return key, cells


def _emit(
    options: Options,
    dialect: CsvDialect,
    schema: Schema,
    layout: _Layout,
    sorter: ExternalSorter,
) -> None:
    """Send the sorted stream to one CSV, or to part files under a directory."""
    if not options.partitioned:
        write_output(options.output, dialect, schema.names, sorter.sorted_rows())
        return
    depth = len(layout.partition_positions)
    limits = Limits(options.max_rows_per_file, options.max_bytes_per_file)
    with staged_directory(options.output) as staging:
        write_parts(
            staging,
            dialect,
            schema.names,
            limits,
            ((tuple(key[:depth]), cells) for key, cells in sorter.sorted_records()),
        )


def _build_sources(options: Options, dialect: CsvDialect) -> list[Source]:
    """Resolve each input path to the format and compression it is read with."""
    return [
        Source(
            path,
            *resolve(path, options.input_format, options.compression),
            dialect=dialect,
            parquet_row_group_bytes=options.parquet_row_group_bytes,
        )
        for path in options.inputs
    ]
