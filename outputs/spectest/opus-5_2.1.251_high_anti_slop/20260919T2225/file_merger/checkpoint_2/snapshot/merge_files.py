#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into one globally sorted CSV.

Usage:
    python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] INPUT ...

Run with ``--help`` for the full option list.

Exit codes:
    0 success
    1 an I/O failure, or a cast rejected by ``--on-type-error fail``
    2 a usage error, including an input whose format cannot be determined
    3 an unusable schema file, or a key column missing from the resolved schema
    5 an input that contradicts its dialect or its compression
    6 a JSON Lines or Parquet input holding nested values
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from csvmerge.casting import TypeErrorPolicy
from csvmerge.dialect import CsvDialect
from csvmerge.errors import MergeError
from csvmerge.merge import MergeConfig, run_merge
from csvmerge.schema import InferMode, SchemaStrategy
from csvmerge.sources import Compression, InputFormat, ReadOptions

DEFAULT_MEMORY_LIMIT_MB = 256
DEFAULT_PARQUET_ROW_GROUP_BYTES = 8 * 1024 * 1024
IO_ERROR_EXIT_CODE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge heterogeneous inputs onto a common schema and sort them by a composite key.",
    )
    parser.add_argument("--output", required=True, metavar="PATH", help="output file, or '-' for stdout")
    parser.add_argument(
        "--key",
        required=True,
        type=_key_list,
        metavar="COL[,COL...]",
        help="comma-separated sort columns, highest precedence first",
    )
    parser.add_argument("--desc", action="store_true", help="sort every key descending")
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing the output columns and types")
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
    args = build_parser().parse_args(argv)
    config = MergeConfig(
        inputs=args.inputs,
        output=args.output,
        keys=args.key,
        descending=args.desc,
        schema_path=args.schema,
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
    try:
        run_merge(config)
    except MergeError as error:
        return _report(error, error.exit_code)
    except OSError as error:
        return _report(error, IO_ERROR_EXIT_CODE)
    return 0


def _report(error: Exception, exit_code: int) -> int:
    print(f"merge_files.py: error: {error}", file=sys.stderr)
    return exit_code


def _key_list(text: str) -> list[str]:
    keys = [name.strip() for name in text.split(",")]
    if not all(keys):
        raise argparse.ArgumentTypeError("--key must be a comma-separated list of column names")
    return keys


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


if __name__ == "__main__":
    sys.exit(main())
