"""Command-line interface."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Options:
    """Everything the run needs, exactly as spelled on the command line."""

    inputs: list[str]
    output: str
    keys: list[str]
    descending: bool
    schema: str | None
    infer: str
    on_type_error: str
    memory_limit_mb: int
    temp_dir: str | None
    quotechar: str
    escapechar: str | None
    null_literal: str


def parse_args(argv: Sequence[str]) -> Options:
    """Parse `argv`, exiting with a usage error if it does not match the interface."""
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV files into a single globally sorted CSV.",
    )
    parser.add_argument("--output", required=True, metavar="PATH|-",
                        help="output file, or - for stdout")
    parser.add_argument("--key", required=True, metavar="col[,col...]",
                        help="composite sort key")
    parser.add_argument("--desc", action="store_true",
                        help="sort every key column descending")
    parser.add_argument("--schema", metavar="SCHEMA_JSON",
                        help="schema JSON document, or a path to one")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict",
                        help="type inference mode when no schema is given")
    parser.add_argument("--on-type-error", choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null", help="what to do with a cell that will not cast")
    parser.add_argument("--memory-limit-mb", type=int, default=64,
                        help="buffer budget before sorting spills to disk")
    parser.add_argument("--temp-dir", metavar="PATH", help="where spill files are created")
    parser.add_argument("--csv-quotechar", default='"', help="input quote character")
    parser.add_argument("--csv-escapechar", help="input escape character")
    parser.add_argument("--csv-null-literal", default="", metavar="STRING",
                        help="text used for null cells")
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    args = parser.parse_args(argv)

    keys = args.key.split(",")
    if not all(keys):
        parser.error("--key must name one or more columns")
    for flag, value in (("--csv-quotechar", args.csv_quotechar),
                        ("--csv-escapechar", args.csv_escapechar)):
        if value is not None and len(value) != 1:
            parser.error(f"{flag} must be a single character")

    return Options(
        inputs=args.inputs,
        output=args.output,
        keys=keys,
        descending=args.desc,
        schema=args.schema,
        infer=args.infer,
        on_type_error=args.on_type_error,
        memory_limit_mb=args.memory_limit_mb,
        temp_dir=args.temp_dir,
        quotechar=args.csv_quotechar,
        escapechar=args.csv_escapechar,
        null_literal=args.csv_null_literal,
    )
