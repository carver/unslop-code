#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.

    python merge_files.py --output merged.csv --key ts,id data/*.csv events.jsonl.gz

Each input is identified by its name and its leading bytes, read as a stream
of rows, and aligned onto a resolved schema - either given with ``--schema``
or inferred from all the inputs together. Every cell is cast to that schema's
types and the rows are sorted by a composite key with a memory-bounded
external sort, so inputs far larger than memory still merge.
"""

from __future__ import annotations

import argparse
import sys
import tempfile

from csvmerge.csvio import InputDialect, write_csv
from csvmerge.errors import MergeError
from csvmerge.formats import AUTO, COMPRESSIONS, INPUT_FORMATS
from csvmerge.records import COERCE_NULL, FAIL, KEEP_STRING, build_records
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
        description="Merge CSV, TSV, JSON Lines and Parquet files onto a common schema "
        "and sort them by one or more key columns.",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help="input files, in precedence order")
    parser.add_argument("--output", required=True, metavar="PATH", help="output file, or - for stdout")
    parser.add_argument("--key", required=True, help="comma separated sort key columns")
    parser.add_argument("--desc", action="store_true", help="sort all key columns descending")
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing output columns and types")
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
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    """Resolve the schema, then stream every input through the sort into the output."""
    dialect = InputDialect(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    options = ReadOptions(dialect, args.parquet_row_group_bytes)
    sources = open_inputs(args.inputs, args.input_format, args.compression, options)
    schema = (
        load_schema(args.schema)
        if args.schema
        else infer_schema(sources, args.infer, args.schema_strategy)
    )
    key_indexes = schema.key_indexes(args.key.split(","))
    budget_bytes = int(args.memory_limit_mb * BYTES_PER_MB * _BUFFER_SHARE)

    with tempfile.TemporaryDirectory(prefix="merge_files-", dir=args.temp_dir) as temp_dir:
        records = build_records(sources, schema, key_indexes, dialect.null_literal, args.on_type_error)
        ordered = sorted_records(records, args.desc, budget_bytes, temp_dir)
        write_csv(args.output, schema.names, (record.cells for record in ordered), dialect)


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
