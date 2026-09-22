"""The merge run: resolve the schema, cast and sort every row, write the output."""
from __future__ import annotations

import tempfile

from .cli import Options
from .csvio import open_output, reader_dialect, write_rows
from .errors import MergeError
from .records import CastPolicy, iter_records
from .schema import Schema, infer_schema, load_schema
from .sorting import ExternalSorter

#: Only part of the memory budget goes to buffered cell text; the rest covers
#: the Python objects wrapping it.
_BUFFER_SHARE = 4


def run(options: Options) -> None:
    """Merge every input into one sorted CSV at the requested destination."""
    dialect = reader_dialect(options.quotechar, options.escapechar)
    policy = CastPolicy(options.on_type_error, options.null_literal)
    schema = _resolve_schema(options, dialect, policy)
    _check_key_columns(schema, options.keys)

    with tempfile.TemporaryDirectory(dir=options.temp_dir, prefix="merge-files-") as spill_dir:
        sorter = ExternalSorter(
            spill_dir,
            options.memory_limit_mb * 1024 * 1024 // _BUFFER_SHARE,
            options.descending,
        )
        for key, row in iter_records(options.inputs, dialect, schema, options.keys, policy):
            sorter.add(key, row)
        # Opened only once every input has been read, so a failed run leaves no
        # partial output behind.
        with open_output(options.output) as stream:
            write_rows(stream, schema.names, sorter.merged())


def _resolve_schema(options: Options, dialect: dict, policy: CastPolicy) -> Schema:
    """An explicit schema when given, otherwise one inferred from the inputs."""
    if options.schema:
        return load_schema(options.schema)
    return infer_schema(options.inputs, dialect, options.infer, policy.is_null)


def _check_key_columns(schema: Schema, keys: list[str]) -> None:
    missing = [key for key in keys if key not in schema.names]
    if missing:
        raise MergeError(f"key column(s) not in the resolved schema: {', '.join(missing)}")
