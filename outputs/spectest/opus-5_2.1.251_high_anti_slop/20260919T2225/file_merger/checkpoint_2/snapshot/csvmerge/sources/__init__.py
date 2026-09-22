"""Readers for the supported input formats, behind one interface.

Every reader turns a file into dictionaries keyed by field name, with missing
values reported as ``None``; CSV and TSV hand over text, JSON Lines and Parquet
hand over already-typed values.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from . import delimited, jsonl, parquet
from .files import Compression, InputFormat, InputSpec, ReadOptions, detect_input
from .scanning import Candidates

__all__ = [
    "Candidates",
    "Compression",
    "InputFormat",
    "InputSpec",
    "ReadOptions",
    "detect_input",
    "read_rows",
    "scan_types",
]

_MODULES = {
    InputFormat.CSV: delimited,
    InputFormat.TSV: delimited,
    InputFormat.JSONL: jsonl,
    InputFormat.PARQUET: parquet,
}


def read_rows(spec: InputSpec, options: ReadOptions) -> Iterator[dict[str, Any]]:
    """Stream one dictionary per row of ``spec``, in file order."""
    return _MODULES[spec.format].read_rows(spec, options)


def scan_types(spec: InputSpec, options: ReadOptions, ignore_nulls: bool) -> Candidates:
    """Report which types each column of ``spec`` could take."""
    return _MODULES[spec.format].scan_types(spec, options, ignore_nulls)
