"""Wiring: resolve the inputs and the schema, cast every record, sort, write."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from csvmerge.cli import Options
from csvmerge.detect import resolve
from csvmerge.dialect import CsvDialect
from csvmerge.inference import infer_schema
from csvmerge.rows import convert_row
from csvmerge.schema import Schema, load_schema
from csvmerge.sorter import ExternalSorter
from csvmerge.sources import Source
from csvmerge.writer import write_output

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
    key_positions = schema.positions_of(options.keys)
    with TemporaryDirectory(dir=options.temp_dir, prefix="csvmerge-") as workspace:
        sorter = ExternalSorter(
            Path(workspace), options.memory_limit_mb * BYTES_PER_MB, options.descending
        )
        _collect(sources, options, schema, dialect, key_positions, sorter)
        write_output(options.output, dialect, schema.names, sorter.sorted_rows())


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


def _collect(
    sources: list[Source],
    options: Options,
    schema: Schema,
    dialect: CsvDialect,
    key_positions: list[int],
    sorter: ExternalSorter,
) -> None:
    """Feed every input record, cast to the schema, into the sorter in file order."""
    for source in sources:
        with source.read() as (_, records):
            for record in records:
                cells, keys = convert_row(record, schema, dialect, options.on_type_error)
                sorter.add([keys[position] for position in key_positions], cells)
