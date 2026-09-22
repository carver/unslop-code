#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into sorted CSV output.

Usage:
    python merge_files.py --output <PATH|-> --key <path>[,<path>...] [options] INPUT ...

Without a partitioning flag the result is one globally sorted CSV. With
``--partition-by``, ``--max-rows-per-file`` or ``--max-bytes-per-file`` the
output is a directory of ``part-xxxxx.csv`` files, optionally under a
Hive-style tree of ``<path>=<value>`` directories.

A ``--schema`` may declare nested columns — ``struct``, ``array<T>``,
``map<string,T>`` and the catch-all ``json`` — which are written as canonical
JSON; ``--key`` and ``--partition-by`` reach into them with field paths such as
``user.id``, ``items.0.sku`` or ``attrs["country"]``.

Run with ``--help`` for the full option list.

Errors are reported on stderr as ``merge_files.py: error: ERR <n> <message>``.

Exit codes:
    0 success
    1 an I/O failure, or a cast rejected by ``--on-type-error fail`` (ERR 4)
    2 a usage error: an unusable --output, an undeterminable input format, a cyclic type alias
    3 an unusable schema, or a key or partition path the schema cannot resolve
    5 an input that contradicts its dialect or its compression
    6 a nested input value with no --schema declaring what it is
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from csvmerge.casting import TypeErrorPolicy
from csvmerge.dialect import CsvDialect
from csvmerge.errors import MergeError
from csvmerge.merge import MergeConfig, run_merge
from csvmerge.paths import FieldPath, parse_paths
from csvmerge.schema import InferMode, SchemaStrategy
from csvmerge.shards import ShardLimits
from csvmerge.sources import Compression, InputFormat, ReadOptions

DEFAULT_MEMORY_LIMIT_MB = 256
DEFAULT_PARQUET_ROW_GROUP_BYTES = 8 * 1024 * 1024
IO_ERROR_EXIT_CODE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge heterogeneous inputs onto a common schema and sort them by a composite key.",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="output file, '-' for stdout, or the output directory when partitioning",
    )
    parser.add_argument(
        "--key",
        required=True,
        type=_field_paths,
        metavar="PATH[,PATH...]",
        help="comma-separated sort field paths, highest precedence first",
    )
    parser.add_argument("--desc", action="store_true", help="sort every key descending")
    parser.add_argument(
        "--partition-by",
        type=_field_paths,
        default=[],
        metavar="PATH[,PATH...]",
        help="comma-separated field paths whose values become Hive-style output directories",
    )
    parser.add_argument(
        "--max-rows-per-file",
        type=_positive_int,
        metavar="INT",
        help="cut each output file after this many data rows",
    )
    parser.add_argument(
        "--max-bytes-per-file",
        type=_positive_int,
        metavar="INT",
        help="cut each output file before it would exceed this many bytes, header included",
    )
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing the output columns and types")
    parser.add_argument(
        "--type-alias-file",
        metavar="ALIASES_JSON",
        help="JSON file of extra type aliases, on top of the built-in ones",
    )
    parser.add_argument(
        "--infer",
        type=InferMode,
        choices=list(InferMode),
        default=InferMode.STRICT,
        metavar="{strict,loose}",
        help="type inference mode when --schema is absent (default: strict)",
    )
    parser.add_argument(
        "--schema-strategy",
        type=SchemaStrategy,
        choices=list(SchemaStrategy),
        default=SchemaStrategy.AUTHORITATIVE,
        metavar="{authoritative,consensus,union}",
        help="how to settle columns whose inputs disagree (default: authoritative)",
    )
    parser.add_argument(
        "--on-type-error",
        type=TypeErrorPolicy,
        choices=list(TypeErrorPolicy),
        default=TypeErrorPolicy.COERCE_NULL,
        metavar="{coerce-null,fail,keep-string}",
        help="what to do with a cell that fails to cast (default: coerce-null)",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=DEFAULT_MEMORY_LIMIT_MB,
        metavar="INT",
        help=f"memory budget for buffered rows (default: {DEFAULT_MEMORY_LIMIT_MB})",
    )
    parser.add_argument("--temp-dir", metavar="PATH", help="directory for sort spill files")
    parser.add_argument(
        "--csv-quotechar", type=_single_char, default='"', metavar="CHAR", help="quote character (default: \")"
    )
    parser.add_argument(
        "--csv-escapechar",
        type=_single_char,
        default=None,
        metavar="CHAR",
        help="escape character; by default quotes are escaped by doubling them",
    )
    parser.add_argument("--csv-null-literal", default="", metavar="STRING", help="text used for missing values")
    parser.add_argument(
        "--input-format",
        type=InputFormat,
        choices=list(InputFormat),
        default=InputFormat.AUTO,
        metavar="{auto,csv,tsv,jsonl,parquet}",
        help="force one format for every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--compression",
        type=Compression,
        choices=list(Compression),
        default=Compression.AUTO,
        metavar="{auto,none,gzip}",
        help="force the compression of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=DEFAULT_PARQUET_ROW_GROUP_BYTES,
        metavar="INT",
        help=f"advisory batch size when reading Parquet (default: {DEFAULT_PARQUET_ROW_GROUP_BYTES})",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = MergeConfig(
        inputs=args.inputs,
        output=args.output,
        keys=args.key,
        descending=args.desc,
        partition_by=args.partition_by,
        limits=ShardLimits(max_rows=args.max_rows_per_file, max_bytes=args.max_bytes_per_file),
        schema_path=args.schema,
        alias_path=args.type_alias_file,
        infer_mode=args.infer,
        strategy=args.schema_strategy,
        policy=args.on_type_error,
        memory_limit_mb=args.memory_limit_mb,
        temp_dir=args.temp_dir,
        options=ReadOptions(
            dialect=CsvDialect(
                quotechar=args.csv_quotechar,
                escapechar=args.csv_escapechar,
                null_literal=args.csv_null_literal,
            ),
            parquet_row_group_bytes=args.parquet_row_group_bytes,
        ),
        input_format=args.input_format,
        compression=args.compression,
    )
    _check_output(parser, config)
    try:
        run_merge(config)
    except MergeError as error:
        return _report(error, error.code, error.exit_code)
    except OSError as error:
        return _report(error, IO_ERROR_EXIT_CODE, IO_ERROR_EXIT_CODE)
    return 0


def _report(error: Exception, code: int, exit_code: int) -> int:
    """Report a failure as ``ERR <n> <message>``, and return the process exit code."""
    print(f"merge_files.py: error: ERR {code} {error}", file=sys.stderr)
    return exit_code


def _check_output(parser: argparse.ArgumentParser, config: MergeConfig) -> None:
    """Reject an output that cannot hold the tree of part files the flags ask for."""
    if not config.writes_directory:
        return
    if config.output == "-":
        parser.error("--output must be a directory when partitioning, not '-'")
    if os.path.exists(config.output) and not os.path.isdir(config.output):
        parser.error(f"--output {config.output!r} exists and is not a directory")


def _field_paths(text: str) -> list[FieldPath]:
    """Parse a comma-separated list of field paths, as ``--key`` and friends take."""
    try:
        return parse_paths(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}")
    return int(text)


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


if __name__ == "__main__":
    sys.exit(main())
