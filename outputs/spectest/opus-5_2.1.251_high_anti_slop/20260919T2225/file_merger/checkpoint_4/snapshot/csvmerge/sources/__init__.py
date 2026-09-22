"""Readers for the supported input formats, behind one interface.

Every reader turns a file into :class:`~csvmerge.sources.rows.SourceRow` values
keyed by field name, with anything missing reported as ``None``; CSV and TSV
hand over text, JSON Lines and Parquet hand over already-typed values.
"""

from __future__ import annotations

from collections.abc import Iterator

from . import delimited, jsonl, parquet
from .files import Compression, InputFormat, InputSpec, ReadOptions, detect_input
from .rows import SourceRow
from .scanning import Candidates

__all__ = [
    "Candidates",
    "Compression",
    "InputFormat",
    "InputSpec",
    "ReadOptions",
    "SourceRow",
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


def read_rows(spec: InputSpec, options: ReadOptions, allow_nested: bool) -> Iterator[SourceRow]:
    """Stream one row of ``spec`` at a time, in file order.

    ``allow_nested`` is set once a ``--schema`` says what nested values mean;
    without one the formats that can carry them reject them outright.
    """
    return _MODULES[spec.format].read_rows(spec, options, allow_nested)


def scan_types(spec: InputSpec, options: ReadOptions, ignore_nulls: bool) -> Candidates:
    """Report which types each column of ``spec`` could take."""
    return _MODULES[spec.format].scan_types(spec, options, ignore_nulls)
