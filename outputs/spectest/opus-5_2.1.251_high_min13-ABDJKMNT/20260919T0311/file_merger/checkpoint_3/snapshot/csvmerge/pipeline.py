"""The merge run: resolve the inputs and schema, cast and sort, write the output."""
from __future__ import annotations

import tempfile
from typing import Iterable

from .cli import Options
from .csvio import open_output, write_rows
from .errors import EXIT_SCHEMA, MergeError
from .formats import resolve_input
from .inference import infer_schema
from .records import CastPolicy, iter_records
from .schema import Schema, load_schema
from .sink import ShardedWriter, ShardLimits, staged_directory
from .sorting import ExternalSorter

#: Only part of the memory budget goes to buffered cell text; the rest covers
#: the Python objects wrapping it.
_BUFFER_SHARE = 4


def run(options: Options) -> None:
    """Merge every input into one sorted CSV at the requested destination."""
    inputs = [resolve_input(path, options.input_format, options.compression)
              for path in options.inputs]
    policy = CastPolicy(options.on_type_error, options.null_literal)
    schema = _resolve_schema(options, inputs, policy)
    _check_columns(schema, options.keys, "key")
    _check_columns(schema, options.partition_by, "partition")

    with tempfile.TemporaryDirectory(dir=options.temp_dir, prefix="merge-files-") as spill_dir:
        sorter = ExternalSorter(
            spill_dir,
            options.memory_limit_mb * 1024 * 1024 // _BUFFER_SHARE,
            options.descending,
        )
        for key, row in iter_records(inputs, options, schema, options.keys, policy,
                                     options.partition_by):
            sorter.add(key, row)
        # The destination is touched only once every input has been read, so a
        # failed run leaves no partial output behind.
        if options.writes_directory:
            _write_tree(options, schema, sorter.merged())
        else:
            with open_output(options.output) as stream:
                write_rows(stream, schema.names, (row for _, row in sorter.merged()))


def _write_tree(options: Options, schema: Schema,
                records: Iterable[tuple[list, list[str]]]) -> None:
    """Write the sorted stream as a tree of part files under `--output`.

    Each record's key leads with its partition directory, which is the output
    root itself when no `--partition-by` was given.
    """
    limits = ShardLimits(options.max_rows_per_file, options.max_bytes_per_file)
    with staged_directory(options.output) as staging:
        with ShardedWriter(staging, schema.names, limits) as writer:
            if not options.partition_by:
                writer.begin("")
            for key, row in records:
                writer.write(key[0], row)


def _resolve_schema(options: Options, inputs: list, policy: CastPolicy) -> Schema:
    """An explicit schema when given, otherwise one inferred from the inputs."""
    if options.schema:
        return load_schema(options.schema)
    return infer_schema(inputs, options, policy)


def _check_columns(schema: Schema, names: list[str], role: str) -> None:
    """Every `--key` and `--partition-by` column must exist in the output."""
    missing = [name for name in names if name not in schema.names]
    if missing:
        raise MergeError(
            f"{role} column(s) not in the resolved schema: {', '.join(missing)}", EXIT_SCHEMA
        )
