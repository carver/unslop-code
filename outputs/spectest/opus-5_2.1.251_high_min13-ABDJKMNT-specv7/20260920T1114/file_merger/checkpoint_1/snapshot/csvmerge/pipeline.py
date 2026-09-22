"""Wiring: resolve the schema, cast every input row, sort, write."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from csvmerge.cli import Options
from csvmerge.inference import infer_schema
from csvmerge.reader import InputDialect, iter_aligned_rows
from csvmerge.rows import convert_row
from csvmerge.schema import Schema, load_schema
from csvmerge.sorter import ExternalSorter
from csvmerge.writer import write_output

BYTES_PER_MB = 1024 * 1024


def run(options: Options) -> None:
    """Execute one merge; raises MergeError for anything the user must fix."""
    dialect = InputDialect(options.quotechar, options.escapechar, options.null_literal)
    schema = (
        load_schema(options.schema)
        if options.schema
        else infer_schema(options.inputs, options.infer, dialect)
    )
    key_positions = schema.positions_of(options.keys)
    with TemporaryDirectory(dir=options.temp_dir, prefix="csvmerge-") as workspace:
        sorter = ExternalSorter(
            Path(workspace), options.memory_limit_mb * BYTES_PER_MB, options.descending
        )
        _collect(options, schema, dialect, key_positions, sorter)
        write_output(options.output, schema.names, sorter.sorted_rows())


def _collect(
    options: Options,
    schema: Schema,
    dialect: InputDialect,
    key_positions: list[int],
    sorter: ExternalSorter,
) -> None:
    """Feed every input row, cast to the schema, into the sorter in file order."""
    for path in options.inputs:
        for raw_cells in iter_aligned_rows(path, dialect, schema.names):
            cells, keys = convert_row(raw_cells, schema, dialect, options.on_type_error)
            sorter.add([keys[position] for position in key_positions], cells)
