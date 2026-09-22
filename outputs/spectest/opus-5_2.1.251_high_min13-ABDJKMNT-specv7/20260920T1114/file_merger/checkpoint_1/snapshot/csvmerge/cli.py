"""Command-line parsing for merge_files.py."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from csvmerge.inference import LOOSE, STRICT
from csvmerge.rows import COERCE_NULL, FAIL, KEEP_STRING

DEFAULT_MEMORY_LIMIT_MB = 64


@dataclass(frozen=True)
class Options:
    """Everything one run of the tool needs, already validated by argparse."""

    output: str
    keys: list[str]
    inputs: list[str]
    descending: bool
    schema: str | None
    infer: str
    on_type_error: str
    memory_limit_mb: int
    temp_dir: str | None
    quotechar: str
    escapechar: str
    null_literal: str


def parse_args(argv: list[str]) -> Options:
    """Build `Options` from the command line, exiting on malformed arguments."""
    parser = _build_parser()
    namespace = parser.parse_args(argv)
    return Options(
        output=namespace.output,
        keys=namespace.key.split(","),
        inputs=namespace.inputs,
        descending=namespace.desc,
        schema=namespace.schema,
        infer=namespace.infer,
        on_type_error=namespace.on_type_error,
        memory_limit_mb=namespace.memory_limit_mb,
        temp_dir=namespace.temp_dir,
        quotechar=namespace.csv_quotechar,
        escapechar=namespace.csv_escapechar,
        null_literal=namespace.csv_null_literal,
    )


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV inputs into one schema-aligned, globally sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument("--key", required=True, help="comma-separated sort key columns")
    parser.add_argument(
        "--desc", action="store_true", help="sort all key columns descending"
    )
    parser.add_argument("--schema", help="JSON file fixing the output schema and order")
    parser.add_argument(
        "--infer",
        choices=(STRICT, LOOSE),
        default=STRICT,
        help="type inference mode used when --schema is absent",
    )
    parser.add_argument(
        "--on-type-error",
        choices=(COERCE_NULL, FAIL, KEEP_STRING),
        default=COERCE_NULL,
        help="what to do with a cell that does not cast",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=DEFAULT_MEMORY_LIMIT_MB,
        help="approximate row buffer size before sorted chunks spill to disk",
    )
    parser.add_argument("--temp-dir", help="directory to hold intermediate spill files")
    parser.add_argument("--csv-quotechar", type=_single_char, default='"')
    parser.add_argument("--csv-escapechar", type=_single_char, default="\\")
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return parser
