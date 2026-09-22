"""The merge run: resolve the inputs and schema, cast and sort, write the output."""
from __future__ import annotations

import tempfile
from typing import Iterable

from .aliases import load_aliases
from .cli import Options
from .csvio import open_output, write_rows
from .formats import resolve_input
from .inference import infer_schema
from .paths import FieldPath, resolve_paths
from .records import iter_records
from .schema import Schema, load_schema
from .sink import ShardedWriter, ShardLimits, staged_directory
from .sorting import ExternalSorter
from .values import CastPolicy

#: Only part of the memory budget goes to buffered cell text; the rest covers
#: the Python objects wrapping it.
_BUFFER_SHARE = 4


def run(options: Options) -> None:
    """Merge every input into one sorted CSV at the requested destination."""
    inputs = [resolve_input(path, options.input_format, options.compression)
              for path in options.inputs]
    policy = CastPolicy(options.on_type_error, options.null_literal)
    schema = _resolve_schema(options, inputs, policy)
    keys = resolve_paths(options.keys, schema, "key")
    partitions = resolve_paths(options.partition_by, schema, "partition")

    with tempfile.TemporaryDirectory(dir=options.temp_dir, prefix="merge-files-") as spill_dir:
        sorter = ExternalSorter(
            spill_dir,
            options.memory_limit_mb * 1024 * 1024 // _BUFFER_SHARE,
            options.descending,
        )
        for key, row in iter_records(inputs, options, schema, keys, policy, partitions):
            sorter.add(key, row)
        # The destination is touched only once every input has been read, so a
        # failed run leaves no partial output behind.
        if options.writes_directory:
            _write_tree(options, schema, partitions, sorter.merged())
        else:
            with open_output(options.output) as stream:
                write_rows(stream, schema.names, (row for _, row in sorter.merged()))


def _write_tree(options: Options, schema: Schema, partitions: list[FieldPath],
                records: Iterable[tuple[list, list[str]]]) -> None:
    """Write the sorted stream as a tree of part files under `--output`.

    Each record's key leads with its partition directory, which is the output
    root itself when no `--partition-by` was given.
    """
    limits = ShardLimits(options.max_rows_per_file, options.max_bytes_per_file)
    with staged_directory(options.output) as staging:
        with ShardedWriter(staging, schema.names, limits) as writer:
            if not partitions:
                writer.begin("")
            for key, row in records:
                writer.write(key[0], row)


def _resolve_schema(options: Options, inputs: list, policy: CastPolicy) -> Schema:
    """An explicit schema when given, otherwise one inferred from the inputs."""
    if options.schema:
        return load_schema(options.schema, load_aliases(options.type_alias_file))
    return infer_schema(inputs, options, policy)
