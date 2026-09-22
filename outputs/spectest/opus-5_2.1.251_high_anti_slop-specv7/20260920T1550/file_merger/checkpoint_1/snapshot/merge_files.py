#!/usr/bin/env python3
"""Merge several CSV files into one schema-aligned, globally sorted CSV.

    python merge_files.py --output merged.csv --key id data/*.csv

The inputs are read once (twice when the schema has to be inferred), cast into
the resolved schema, sorted with a bounded-memory external sort and written as
a single RFC-4180 CSV.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from csv_io import OUTPUT_DIALECT, CsvOptions, open_csv, open_output
from errors import MergeError
from external_sort import ExternalSorter
from rows import RowShaper
from schema import Column, infer_schema, load_schema

_BYTES_PER_MB = 1024 * 1024


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV files into one sorted CSV with a common schema.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, metavar="INPUT.csv")
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument("--key", required=True, help="comma separated sort columns")
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", type=Path, help="JSON file with the exact output schema")
    parser.add_argument(
        "--infer",
        choices=("strict", "loose"),
        default="strict",
        help="how to infer types when no schema is given (default: strict)",
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
    return parser.parse_args(argv)


def resolve_key_columns(columns: list[Column], key: str) -> list[str]:
    """Split ``--key`` and check every name against the resolved schema."""
    names = [name.strip() for name in key.split(",") if name.strip()]
    if not names:
        raise MergeError("--key needs at least one column name")
    known = {column.name for column in columns}
    missing = [name for name in names if name not in known]
    if missing:
        raise MergeError(f"key column(s) not in the resolved schema: {', '.join(missing)}")
    return names


def merge(args: argparse.Namespace, options: CsvOptions, columns: list[Column]) -> None:
    """Cast every input row into ``columns``, sort them and write the result."""
    shaper = RowShaper(columns, resolve_key_columns(columns, args.key), args.on_type_error, options)
    budget = args.memory_limit_mb * _BYTES_PER_MB
    with ExternalSorter(args.desc, budget, args.temp_dir) as sorter:
        for path in args.inputs:
            with open_csv(path, options) as (_header, records):
                for record in records:
                    sorter.add(*shaper.shape(record))
        with open_output(args.output) as stream:
            writer = csv.writer(stream, **OUTPUT_DIALECT)
            writer.writerow([column.name for column in columns])
            writer.writerows(sorter.sorted_rows())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = CsvOptions(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    try:
        columns = (
            load_schema(args.schema)
            if args.schema
            else infer_schema(args.inputs, options, args.infer)
        )
        merge(args, options, columns)
    except (MergeError, OSError, UnicodeDecodeError, csv.Error) as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
