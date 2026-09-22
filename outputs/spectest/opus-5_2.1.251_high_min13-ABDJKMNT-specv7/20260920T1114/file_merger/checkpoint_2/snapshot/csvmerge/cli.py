"""Command-line parsing for merge_files.py."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from csvmerge.detect import AUTO, COMPRESSIONS, FORMATS
from csvmerge.inference import LOOSE, STRICT
from csvmerge.parquetio import DEFAULT_ROW_GROUP_BYTES
from csvmerge.rows import COERCE_NULL, FAIL, KEEP_STRING
from csvmerge.strategies import AUTHORITATIVE, CONSENSUS, UNION

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
    schema_strategy: str
    on_type_error: str
    memory_limit_mb: int
    temp_dir: str | None
    quotechar: str
    escapechar: str
    null_literal: str
    input_format: str
    compression: str
    parquet_row_group_bytes: int


def parse_args(argv: list[str]) -> Options:
    """Build `Options` from the command line, exiting on malformed arguments."""
    namespace = _build_parser().parse_args(argv)
    return Options(
        output=namespace.output,
        keys=namespace.key.split(","),
        inputs=namespace.inputs,
        descending=namespace.desc,
        schema=namespace.schema,
        infer=namespace.infer,
        schema_strategy=namespace.schema_strategy,
        on_type_error=namespace.on_type_error,
        memory_limit_mb=namespace.memory_limit_mb,
        temp_dir=namespace.temp_dir,
        quotechar=namespace.csv_quotechar,
        escapechar=namespace.csv_escapechar,
        null_literal=namespace.csv_null_literal,
        input_format=namespace.input_format,
        compression=namespace.compression,
        parquet_row_group_bytes=namespace.parquet_row_group_bytes,
    )


def _single_char(text: str) -> str:
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected a single character, got {text!r}")
    return text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.",
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
        "--schema-strategy",
        choices=(AUTHORITATIVE, CONSENSUS, UNION),
        default=AUTHORITATIVE,
        help="how inputs that disagree about a column's type are reconciled",
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
    parser.add_argument(
        "--input-format",
        choices=(AUTO, *FORMATS),
        default=AUTO,
        help="format of every input, or auto to detect each one",
    )
    parser.add_argument(
        "--compression",
        choices=(AUTO, *COMPRESSIONS),
        default=AUTO,
        help="compression of every input, or auto to detect each one",
    )
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=DEFAULT_ROW_GROUP_BYTES,
        help="advisory byte budget for one Parquet read batch",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser
