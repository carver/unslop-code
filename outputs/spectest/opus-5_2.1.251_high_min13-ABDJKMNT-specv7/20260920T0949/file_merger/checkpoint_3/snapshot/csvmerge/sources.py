"""One entry point onto the four input formats."""

from __future__ import annotations

from .jsonl import open_jsonl
from .parquet import open_parquet
from .reader import CsvFormat, open_delimited


def open_records(spec, fmt: CsvFormat):
    """Context manager yielding the records of one input, whatever its format."""
    if spec.format == "jsonl":
        return open_jsonl(spec)
    if spec.format == "parquet":
        return open_parquet(spec)
    return open_delimited(spec, fmt)
