#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.

    python merge_files.py --output merged.csv --key ts,id users.csv events.jsonl.gz

Every input is resolved to a format and a compression, read once (twice when
the schema has to be inferred), cast into the resolved schema, sorted with a
bounded-memory external sort and written as a single RFC-4180 CSV.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
import zlib
from pathlib import Path

from csv_io import CsvOptions, open_output, output_dialect
from errors import DataError, KeyColumnError, MergeError
from external_sort import ExternalSorter
from parquet_io import PARQUET_ERRORS
from rows import RowShaper
from schema import STRATEGIES, Column, infer_schema, load_schema
from sources import COMPRESSIONS, FORMATS, ReadOptions, Reader, open_source

_BYTES_PER_MB = 1024 * 1024

# Failures that mean an input is malformed rather than the invocation being
# wrong: a broken dialect, encoding, gzip stream or Parquet file.  EOFError is
# how a truncated gzip stream surfaces, and gzip.BadGzipFile is an OSError, so
# both have to be matched before OSError is.
_DATA_ERRORS = (
    csv.Error,
    UnicodeDecodeError,
    EOFError,
    gzip.BadGzipFile,
    zlib.error,
    *PARQUET_ERRORS,
)


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet files into one sorted CSV.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, metavar="INPUT")
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument("--key", required=True, help="comma separated sort columns")
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", type=Path, help="JSON file with the exact output schema")
    parser.add_argument(
        "--infer",
        choices=("strict", "loose"),
        default="strict",
        help="how to settle a type the inputs disagree on (default: strict)",
    )
    parser.add_argument(
        "--schema-strategy",
        choices=STRATEGIES,
        default="authoritative",
        help="which inputs decide an inferred type (default: authoritative)",
    )
    parser.add_argument(
        "--on-type-error",
        choices=("coerce-null", "fail", "keep-string"),
        default="coerce-null",
        help="what to do with a cell that does not fit its type (default: coerce-null)",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=128,
        help="approximate memory the sort may use before spilling (default: 128)",
    )
    parser.add_argument("--temp-dir", type=Path, help="directory to hold the spilled runs")
    parser.add_argument("--csv-quotechar", type=_single_char, default='"')
    parser.add_argument("--csv-escapechar", type=_single_char, default="\\")
    parser.add_argument("--csv-null-literal", default="", help="text used for missing values")
    parser.add_argument(
        "--input-format",
        choices=("auto", *FORMATS),
        default="auto",
        help="format of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--compression",
        choices=("auto", *COMPRESSIONS),
        default="auto",
        help="compression of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=8 * _BYTES_PER_MB,
        help="advisory bytes per Parquet read batch (default: 8388608)",
    )
    return parser.parse_args(argv)


def resolve_key_columns(columns: list[Column], key: str) -> list[str]:
    """Split ``--key`` and check every name against the resolved schema."""
    names = [name.strip() for name in key.split(",") if name.strip()]
    if not names:
        raise KeyColumnError("--key needs at least one column name")
    known = {column.name for column in columns}
    missing = [name for name in names if name not in known]
    if missing:
        raise KeyColumnError(f"key column(s) not in the resolved schema: {', '.join(missing)}")
    return names


def merge(
    args: argparse.Namespace,
    options: CsvOptions,
    columns: list[Column],
    readers: list[Reader],
) -> None:
    """Cast every input row into ``columns``, sort them and write the result."""
    shaper = RowShaper(columns, resolve_key_columns(columns, args.key), args.on_type_error, options)
    budget = args.memory_limit_mb * _BYTES_PER_MB
    with ExternalSorter(args.desc, budget, args.temp_dir) as sorter:
        for reader in readers:
            for record in reader.records():
                sorter.add(*shaper.shape(record))
        with open_output(args.output) as stream:
            writer = csv.writer(stream, **output_dialect(options))
            writer.writerow([column.name for column in columns])
            writer.writerows(sorter.sorted_rows())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    csv_options = CsvOptions(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    options = ReadOptions(csv_options, args.parquet_row_group_bytes)
    try:
        readers = [
            open_source(path, args.input_format, args.compression, options) for path in args.inputs
        ]
        columns = (
            load_schema(args.schema)
            if args.schema
            else infer_schema(readers, args.infer, args.schema_strategy)
        )
        merge(args, csv_options, columns, readers)
    except MergeError as error:
        return _report(error, error.exit_code)
    except _DATA_ERRORS as error:
        return _report(error, DataError.exit_code)
    except OSError as error:
        return _report(error, MergeError.exit_code)
    return 0


def _report(error: Exception, exit_code: int) -> int:
    print(f"merge_files.py: error: {error}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
