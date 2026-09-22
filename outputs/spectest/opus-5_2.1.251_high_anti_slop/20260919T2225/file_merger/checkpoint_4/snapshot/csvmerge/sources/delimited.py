"""Reading the text formats: RFC-4180 CSV and unquoted TSV."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

from ..errors import MalformedInputError
from .files import InputFormat, InputSpec, ReadOptions, open_text
from .rows import SourceRow
from .scanning import Candidates, accumulate


def read_rows(spec: InputSpec, options: ReadOptions, _allow_nested: bool) -> Iterator[SourceRow]:
    """Yield one row per data line, with null cells reported as ``None``.

    Text cells are never nested in themselves: a JSON literal only becomes a
    structure once it is cast to a nested type.
    """
    with _open(spec, options) as (_header, rows):
        yield from rows


def scan_types(spec: InputSpec, options: ReadOptions, ignore_nulls: bool) -> Candidates:
    """Report the types each column of this file could take."""
    with _open(spec, options) as (header, rows):
        return accumulate(rows, ignore_nulls, header)


@contextmanager
def _open(spec: InputSpec, options: ReadOptions) -> Iterator[tuple[list[str], Iterator[SourceRow]]]:
    with open_text(spec) as stream:
        reader = _reader(stream, spec.format, options)
        header = next(reader, [])
        yield header, _rows(reader, header, spec, options)


def _reader(stream: IO[str], input_format: InputFormat, options: ReadOptions) -> Iterator[list[str]]:
    """TSV is tab-separated and never quoted; CSV follows the configured dialect."""
    if input_format is InputFormat.TSV:
        return csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
    return options.dialect.reader(stream)


def _rows(
    reader: Iterator[list[str]], header: list[str], spec: InputSpec, options: ReadOptions
) -> Iterator[SourceRow]:
    """Project raw rows onto the header, skipping blank lines.

    A TSV row whose width does not match the header can only come from a literal
    tab inside a field, which the format has no way to escape.
    """
    is_null = options.dialect.is_null
    for row in reader:
        if not row:
            continue
        if spec.format is InputFormat.TSV and len(row) != len(header):
            raise MalformedInputError(
                f"{spec.path}: expected {len(header)} tab-separated fields, found {len(row)}"
            )
        values = {name: None if is_null(text) else text for name, text in zip(header, row)}
        yield SourceRow(values, reader.line_num)
