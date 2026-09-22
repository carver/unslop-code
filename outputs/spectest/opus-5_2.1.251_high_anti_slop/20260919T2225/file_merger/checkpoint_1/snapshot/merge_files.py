#!/usr/bin/env python3
"""Merge multiple CSV files into one globally sorted CSV.

Usage:
    python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] INPUT.csv ...

Run with ``--help`` for the full option list.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from csvmerge.casting import TypeErrorPolicy
from csvmerge.dialect import CsvDialect
from csvmerge.errors import MergeError
from csvmerge.merge import MergeConfig, run_merge
from csvmerge.schema import InferMode

DEFAULT_MEMORY_LIMIT_MB = 256


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge UTF-8 CSV files onto a common schema and sort them by a composite key.",
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
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
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
        policy=args.on_type_error,
        memory_limit_mb=args.memory_limit_mb,
        temp_dir=args.temp_dir,
        dialect=CsvDialect(
            quotechar=args.csv_quotechar,
            escapechar=args.csv_escapechar,
            null_literal=args.csv_null_literal,
        ),
    )
    try:
        run_merge(config)
    except MergeError as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return 1
    return 0


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
