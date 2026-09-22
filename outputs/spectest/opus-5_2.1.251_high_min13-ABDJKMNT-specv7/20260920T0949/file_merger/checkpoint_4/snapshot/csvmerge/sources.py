"""One entry point onto the four input formats."""

from __future__ import annotations

from .jsonl import open_jsonl
from .parquet import open_parquet
from .reader import CsvFormat, open_delimited


def open_records(spec, fmt: CsvFormat, nested_ok: bool):
    """Context manager yielding the records of one input, whatever its format.

    ``nested_ok`` says whether a ``--schema`` is there to declare the shape of
    a nested value; without one the JSON-shaped formats refuse nesting.
    """
    if spec.format == "jsonl":
        return open_jsonl(spec, nested_ok)
    if spec.format == "parquet":
        return open_parquet(spec, nested_ok)
    return open_delimited(spec, fmt)
