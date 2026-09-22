#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.

    python merge_files.py --output merged.csv --key id data/*.csv inputs/*.jsonl

See ``--help`` for the full interface.  The heavy lifting lives in the
``csvmerge`` package: format detection, schema resolution, casting and the
external sort.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from csvmerge.errors import MergeError, UsageError
from csvmerge.formats import (
    DEFAULT_ROW_GROUP_BYTES,
    Compression,
    FileFormat,
    InputDialect,
    describe,
)
from csvmerge.merge import MergeConfig, TypeErrorPolicy, merge
from csvmerge.schema import InferMode, SchemaStrategy


def _char(text: str) -> str:
    """Argparse type for a single-character dialect option."""
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


def _optional_char(text: str) -> str | None:
    """Like :func:`_char`, but ``''`` means "no escape character"."""
    return _char(text) if text else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet files into one sorted CSV.",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help="input files")
    parser.add_argument(
        "--output", required=True, metavar="PATH|-", help="output file, or - for stdout"
    )
    parser.add_argument(
        "--key",
        required=True,
        action="append",
        metavar="COL[,COL...]",
        help="sort column(s); repeatable and comma separated",
    )
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", metavar="SCHEMA_JSON", help="JSON file fixing columns and types")
    parser.add_argument(
        "--infer",
        choices=[mode.value for mode in InferMode],
        default=InferMode.STRICT.value,
        help="type inference mode when no schema is given (default: strict)",
    )
    parser.add_argument(
        "--schema-strategy",
        choices=[strategy.value for strategy in SchemaStrategy],
        default=SchemaStrategy.AUTHORITATIVE.value,
        help="how to settle inferred types when inputs disagree (default: authoritative)",
    )
    parser.add_argument(
        "--on-type-error",
        choices=[policy.value for policy in TypeErrorPolicy],
        default=TypeErrorPolicy.COERCE_NULL.value,
        help="what to do with cells that fail to cast (default: coerce-null)",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=256,
        help="memory the sort may use before spilling to disk (default: 256)",
    )
    parser.add_argument("--temp-dir", metavar="PATH", help="directory for spill files")
    parser.add_argument(
        "--csv-quotechar", type=_char, default='"', help="input quote character"
    )
    parser.add_argument(
        "--csv-escapechar",
        type=_optional_char,
        default="\\",
        help="input escape character; pass '' to accept only doubled quotes",
    )
    parser.add_argument(
        "--csv-null-literal", default="", help="text meaning null, on input and output"
    )
    parser.add_argument(
        "--input-format",
        choices=[file_format.value for file_format in FileFormat],
        default=FileFormat.AUTO.value,
        help="format of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--compression",
        choices=[compression.value for compression in Compression],
        default=Compression.AUTO.value,
        help="compression of every input (default: auto, detected per file)",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=DEFAULT_ROW_GROUP_BYTES,
        help=f"advisory Parquet batch size in bytes (default: {DEFAULT_ROW_GROUP_BYTES})",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> MergeConfig:
    """Turn parsed arguments into the configuration the merge runs on."""
    keys = [name for group in args.key for name in group.split(",") if name]
    if not keys:
        raise UsageError("--key needs at least one column name")
    dialect = InputDialect(
        quotechar=args.csv_quotechar,
        escapechar=args.csv_escapechar,
        null_literal=args.csv_null_literal,
    )
    sources = [
        describe(
            path,
            FileFormat(args.input_format),
            Compression(args.compression),
            dialect,
            args.parquet_row_group_bytes,
        )
        for path in args.inputs
    ]
    return MergeConfig(
        sources=sources,
        output=args.output,
        keys=keys,
        descending=args.desc,
        schema_path=args.schema,
        infer_mode=InferMode(args.infer),
        schema_strategy=SchemaStrategy(args.schema_strategy),
        on_type_error=TypeErrorPolicy(args.on_type_error),
        memory_limit_mb=args.memory_limit_mb,
        temp_dir=args.temp_dir,
        null_literal=args.csv_null_literal,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        merge(config_from_args(args))
    except MergeError as error:
        print(f"merge_files.py: {error}", file=sys.stderr)
        return error.exit_code
    except OSError as error:
        print(f"merge_files.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
