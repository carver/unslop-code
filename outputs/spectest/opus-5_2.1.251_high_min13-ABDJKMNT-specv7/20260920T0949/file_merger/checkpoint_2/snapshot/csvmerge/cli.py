"""Argument parsing and top-level wiring of the merge."""

from __future__ import annotations

import argparse
import sys

from .errors import ToolError
from .formats import COMPRESSIONS, FORMATS, resolve_source
from .inference import infer_schema
from .pipeline import prepared_rows
from .reader import CsvFormat
from .schema import load_schema
from .sorting import budget_bytes, sort_rows
from .writer import open_output, write_csv

DEFAULT_MEMORY_LIMIT_MB = 64
DEFAULT_ROW_GROUP_BYTES = 8 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, metavar="PATH|-", help="output file, or - for stdout")
    parser.add_argument(
        "--key",
        required=True,
        action="append",
        metavar="COL[,COL...]",
        help="sort key columns, most significant first",
    )
    parser.add_argument("--desc", action="store_true", help="sort every key column descending")
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing the output columns and types")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict", help="type inference mode")
    parser.add_argument(
        "--schema-strategy",
        choices=("authoritative", "consensus", "union"),
        default="authoritative",
        help="how to settle inputs that disagree about a column's type",
    )
    parser.add_argument(
        "--on-type-error",
        choices=("coerce-null", "fail", "keep-string"),
        default="coerce-null",
        help="what to do with a cell that does not fit its column type",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=DEFAULT_MEMORY_LIMIT_MB,
        metavar="INT",
        help="approximate memory to use before spilling to disk",
    )
    parser.add_argument("--temp-dir", metavar="PATH", help="directory holding the spilled sort runs")
    parser.add_argument("--csv-quotechar", default='"', metavar="CHAR", help="CSV quote character")
    parser.add_argument("--csv-escapechar", default="\\", metavar="CHAR", help="CSV escape character")
    parser.add_argument("--csv-null-literal", default="", metavar="STRING", help="text standing for a null value")
    parser.add_argument(
        "--input-format",
        choices=FORMATS,
        default="auto",
        help="format of every input, or auto to detect each one",
    )
    parser.add_argument(
        "--compression",
        choices=COMPRESSIONS,
        default="auto",
        help="compression of every input, or auto to detect each one",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=DEFAULT_ROW_GROUP_BYTES,
        metavar="INT",
        help="advisory batch size, in bytes, for reading parquet",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


def _csv_format(parser: argparse.ArgumentParser, args: argparse.Namespace) -> CsvFormat:
    """Build the CSV dialect, rejecting multi-character quote/escape flags."""
    if len(args.csv_quotechar) != 1:
        parser.error("--csv-quotechar takes a single character")
    if len(args.csv_escapechar) > 1:
        parser.error("--csv-escapechar takes a single character")
    # An empty --csv-escapechar disables escaping, leaving doubled quotes only.
    return CsvFormat(args.csv_quotechar, args.csv_escapechar or None, args.csv_null_literal)


def _key_columns(parser: argparse.ArgumentParser, args: argparse.Namespace) -> list[str]:
    """Flatten the comma separated (and repeatable) --key values."""
    names = [name for group in args.key for name in group.split(",")]
    if not all(names):
        parser.error("--key takes one or more non-empty column names")
    return names


def run(args: argparse.Namespace, fmt: CsvFormat, keys) -> None:
    """Resolve the inputs and the schema, then stream every row through the sort."""
    specs = [
        resolve_source(path, args.input_format, args.compression, args.parquet_row_group_bytes)
        for path in args.inputs
    ]
    schema = (
        load_schema(args.schema)
        if args.schema
        else infer_schema(specs, fmt, args.infer, args.schema_strategy)
    )
    key_indexes = [schema.index_of(name) for name in keys]

    rows = prepared_rows(specs, schema, fmt, key_indexes, args.on_type_error)
    ordered = sort_rows(rows, args.desc, budget_bytes(args.memory_limit_mb), args.temp_dir)
    with open_output(args.output) as handle:
        write_csv(handle, schema.names, ordered, fmt)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = _csv_format(parser, args)
    keys = _key_columns(parser, args)
    try:
        run(args, fmt, keys)
    except ToolError as exc:
        print(f"merge_files.py: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"merge_files.py: error: {exc}", file=sys.stderr)
        return ToolError.exit_code
    return 0
