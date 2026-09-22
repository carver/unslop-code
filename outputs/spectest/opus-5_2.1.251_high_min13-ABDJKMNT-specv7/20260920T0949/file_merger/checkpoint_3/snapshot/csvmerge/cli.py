"""Argument parsing and top-level wiring of the merge."""

from __future__ import annotations

import argparse
import sys

from .errors import ToolError
from .formats import COMPRESSIONS, FORMATS, resolve_source
from .inference import infer_schema
from .partition import PartitionPlan, write_partitions
from .pipeline import RowBuilder, prepared_rows
from .reader import CsvFormat
from .schema import load_schema
from .shards import ShardLimits
from .sorting import budget_bytes, sort_rows
from .writer import open_output, open_output_directory, write_csv

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
    parser.add_argument(
        "--partition-by",
        action="append",
        metavar="COL[,COL...]",
        help="write one Hive-style directory per combination of these columns' values",
    )
    parser.add_argument(
        "--max-rows-per-file",
        type=int,
        metavar="INT",
        help="cut each output file after this many data rows",
    )
    parser.add_argument(
        "--max-bytes-per-file",
        type=int,
        metavar="INT",
        help="cut each output file before it would exceed this many bytes",
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


def _plan(parser: argparse.ArgumentParser, args: argparse.Namespace) -> PartitionPlan:
    """Build the output plan from the three partitioning flags, and check them."""
    columns = [name for group in args.partition_by or () for name in group.split(",")]
    if not all(columns):
        parser.error("--partition-by takes one or more non-empty column names")
    for flag, limit in (
        ("--max-rows-per-file", args.max_rows_per_file),
        ("--max-bytes-per-file", args.max_bytes_per_file),
    ):
        if limit is not None and limit < 1:
            parser.error(f"{flag} takes a positive integer")

    plan = PartitionPlan(tuple(columns), ShardLimits(args.max_rows_per_file, args.max_bytes_per_file))
    if plan.to_directory and args.output == "-":
        parser.error("--output must be a directory path when a partitioning flag is given, not -")
    return plan


def run(args: argparse.Namespace, fmt: CsvFormat, keys, plan: PartitionPlan) -> None:
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
    builder = RowBuilder(
        schema,
        [schema.index_of(name) for name in keys],
        [schema.index_of(name, "partition") for name in plan.columns],
        args.on_type_error,
        fmt.null_literal,
    )

    rows = prepared_rows(specs, fmt, builder)
    ordered = sort_rows(rows, args.desc, budget_bytes(args.memory_limit_mb), args.temp_dir)
    if plan.to_directory:
        with open_output_directory(args.output) as root:
            write_partitions(root, schema.names, ordered, plan, fmt)
    else:
        with open_output(args.output) as handle:
            write_csv(handle, schema.names, (cells for _, cells in ordered), fmt)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = _csv_format(parser, args)
    keys = _key_columns(parser, args)
    plan = _plan(parser, args)
    try:
        run(args, fmt, keys, plan)
    except ToolError as exc:
        print(f"merge_files.py: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"merge_files.py: error: {exc}", file=sys.stderr)
        return ToolError.exit_code
    return 0
