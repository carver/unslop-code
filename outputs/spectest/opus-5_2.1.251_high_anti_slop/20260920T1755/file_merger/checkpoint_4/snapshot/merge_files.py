#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.

    python merge_files.py --output merged.csv --key ts,id data/*.csv events.jsonl.gz

Each input is identified by its name and its leading bytes, read as a stream
of rows, and aligned onto a resolved schema - either given with ``--schema``
or inferred from all the inputs together. Every cell is cast to that schema's
types, which may be nested structs, arrays and maps that land in the output
as canonical JSON, and the rows are sorted by a composite key of field paths
with a memory-bounded external sort, so inputs far larger than memory still
merge.

The result is a single CSV unless a partitioning flag asks for a directory of
``part-xxxxx.csv`` files, split by partition column values, by row count, by
byte size, or by any combination of the three.
"""

from __future__ import annotations

import argparse
import sys
import tempfile

from csvmerge.aliases import load_aliases
from csvmerge.csvio import STDOUT_TARGET, InputDialect
from csvmerge.errors import MergeError
from csvmerge.formats import AUTO, COMPRESSIONS, INPUT_FORMATS
from csvmerge.nested import COERCE_NULL, FAIL, KEEP_STRING
from csvmerge.output import OutputLayout, write_output
from csvmerge.paths import split_paths
from csvmerge.records import RecordPlan, build_records
from csvmerge.schema import AUTHORITATIVE, STRATEGIES, infer_schema, load_schema
from csvmerge.sources import ReadOptions, open_inputs
from csvmerge.sorting import sorted_records
from csvmerge.values import LOOSE, STRICT

BYTES_PER_MB = 1024 * 1024
# Only part of the limit is spent on buffered rows; the rest covers the
# interpreter itself, the reader and writer buffers, the merge heap, and the
# allocator overhead that measured RSS carries on top of live objects.
_BUFFER_SHARE = 0.4
_DEFAULT_PARQUET_ROW_GROUP_BYTES = 1024 * 1024


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet files onto a common schema, "
        "nested types included, and sort them by one or more key field paths.",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help="input files, in precedence order")
    parser.add_argument("--output", required=True, metavar="PATH", help="output file, or - for stdout")
    parser.add_argument(
        "--key",
        required=True,
        metavar="PATHS",
        help="comma separated sort key field paths, e.g. user.id,ts",
    )
    parser.add_argument("--desc", action="store_true", help="sort all key columns descending")
    parser.add_argument(
        "--partition-by",
        metavar="PATHS",
        help="comma separated field paths whose values become Hive-style output directories",
    )
    parser.add_argument(
        "--max-rows-per-file",
        type=_positive_int,
        metavar="INT",
        help="split the output into files of at most this many data rows",
    )
    parser.add_argument(
        "--max-bytes-per-file",
        type=_positive_int,
        metavar="INT",
        help="split the output into files of at most this many bytes, header included",
    )
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing output columns and types")
    parser.add_argument(
        "--type-alias-file",
        metavar="ALIASES_JSON",
        help="JSON file of extra type aliases, on top of the built-in ones",
    )
    parser.add_argument(
        "--infer",
        choices=(STRICT, LOOSE),
        default=STRICT,
        help="type inference mode used when no schema is given (default: strict)",
    )
    parser.add_argument(
        "--schema-strategy",
        choices=STRATEGIES,
        default=AUTHORITATIVE,
        help="how to settle a column whose type the inputs disagree on (default: authoritative)",
    )
    parser.add_argument(
        "--on-type-error",
        choices=(COERCE_NULL, FAIL, KEEP_STRING),
        default=COERCE_NULL,
        help="what to do with a cell that will not cast (default: coerce-null)",
    )
    parser.add_argument(
        "--memory-limit-mb", type=int, default=256, help="memory ceiling for buffered rows (default: 256)"
    )
    parser.add_argument("--temp-dir", metavar="PATH", help="directory to hold spilled sort runs")
    parser.add_argument("--csv-quotechar", default='"', metavar="CHAR", help="CSV quote character")
    parser.add_argument(
        "--csv-escapechar",
        default=None,
        metavar="CHAR",
        help="CSV escape character; quotes are doubled when unset",
    )
    parser.add_argument(
        "--csv-null-literal", default="", metavar="STRING", help="text standing in for a null value"
    )
    parser.add_argument(
        "--input-format",
        choices=INPUT_FORMATS,
        default=AUTO,
        help="format of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--compression",
        choices=COMPRESSIONS,
        default=AUTO,
        help="compression of every input (default: auto, gzip for a .gz name)",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=_DEFAULT_PARQUET_ROW_GROUP_BYTES,
        help="advisory size of the Parquet batches read at a time (default: 1048576)",
    )
    args = parser.parse_args(argv)
    if args.output == STDOUT_TARGET and layout_of(args).directory:
        parser.error("--output must name a directory when partitioning; stdout takes one CSV only")
    return args


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a positive integer")
    return value


def layout_of(args: argparse.Namespace) -> OutputLayout:
    """Read the partitioning flags as the shape they give the output."""
    return OutputLayout(bool(args.partition_by), args.max_rows_per_file, args.max_bytes_per_file)


def run(args: argparse.Namespace) -> None:
    """Resolve the schema, then stream every input through the sort into the output."""
    dialect = InputDialect(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    options = ReadOptions(dialect, args.parquet_row_group_bytes)
    sources = open_inputs(args.inputs, args.input_format, args.compression, options)
    schema = (
        load_schema(args.schema, load_aliases(args.type_alias_file))
        if args.schema
        else infer_schema(sources, args.infer, args.schema_strategy)
    )
    plan = RecordPlan(
        schema=schema,
        keys=schema.paths_of(split_paths(args.key), "key"),
        partitions=(
            schema.paths_of(split_paths(args.partition_by), "partition")
            if args.partition_by
            else ()
        ),
        null_literal=dialect.null_literal,
        on_type_error=args.on_type_error,
    )
    budget_bytes = int(args.memory_limit_mb * BYTES_PER_MB * _BUFFER_SHARE)

    with tempfile.TemporaryDirectory(prefix="merge_files-", dir=args.temp_dir) as temp_dir:
        records = build_records(sources, plan)
        ordered = sorted_records(records, args.desc, budget_bytes, temp_dir)
        write_output(args.output, schema.names, ordered, dialect, layout_of(args))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except MergeError as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return error.exit_code
    except OSError as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
