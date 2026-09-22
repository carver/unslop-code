"""Reading every supported input as a stream of flat name-to-value mappings.

A source hides what its file looks like on disk: CSV and TSV hand over text,
JSON Lines and Parquet hand over values that already carry a type, and all of
them spell a missing value ``None``. Rows are streamed, so no source holds
more than one line - or one batch of Parquet rows - in memory at a time.
"""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, ClassVar, FrozenSet, Iterator, Mapping, NamedTuple

from csvmerge.csvio import InputDialect
from csvmerge.errors import EXIT_NESTED, EXIT_SOURCE, MergeError
from csvmerge.formats import (
    CSV,
    JSONL,
    PARQUET,
    TSV,
    FormatSpec,
    open_text,
    resolve_format,
)
from csvmerge.values import LOOSE, value_candidates

# JSON has no integer width; anything outside a 64-bit range becomes a float.
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1
_TSV_READER_ARGS = {"delimiter": "\t", "quoting": csv.QUOTE_NONE, "quotechar": None}


@dataclass(frozen=True)
class ReadOptions:
    """Settings the readers take from the command line."""

    dialect: InputDialect
    parquet_row_group_bytes: int


class Row(NamedTuple):
    """One input row: where it came from, and the values it carries by name.

    ``ordinal`` is the line number for text inputs and the row number for
    Parquet; it only ever appears in error messages.
    """

    ordinal: int
    values: Mapping[str, Any]


class Source(ABC):
    """One input file, read as flat mappings with missing values as ``None``."""

    # Whether the format carries types of its own, which schema resolution
    # under ``authoritative`` trusts ahead of anything parsed out of text.
    typed: ClassVar[bool] = False

    def __init__(self, path: str, spec: FormatSpec) -> None:
        self.path = path
        self.spec = spec

    @abstractmethod
    def rows(self) -> Iterator[Row]:
        """Yield every data row of the file, in file order."""

    def declared_columns(self) -> tuple[str, ...]:
        """Columns the file names up front; JSON Lines only reveals them row by row."""
        return ()

    def observe_types(self, mode: str) -> dict[str, FrozenSet[str] | None]:
        """Narrow each column to the types that fit every value in this file.

        A column the file carries but never fills maps to ``None``. In
        ``loose`` mode a missing value is skipped, so a column stays numeric
        or temporal as long as every real value parses; in ``strict`` mode it
        is an observation like any other, and only ``string`` fits it.
        """
        candidates: dict[str, FrozenSet[str] | None] = dict.fromkeys(self.declared_columns())
        for row in self.rows():
            for name, value in row.values.items():
                if mode == LOOSE and value is None:
                    continue
                seen = candidates.get(name)
                fits = value_candidates(value)
                candidates[name] = fits if seen is None else seen & fits
        return candidates


class DelimitedSource(Source):
    """CSV or TSV: a header row naming the columns, then one row per line.

    TSV is read without any quoting, so a literal tab inside a field splits it
    into an extra column; such a row is rejected rather than silently misread.
    """

    def __init__(self, path: str, spec: FormatSpec, dialect: InputDialect, tab_separated: bool) -> None:
        super().__init__(path, spec)
        self._dialect = dialect
        self._tab_separated = tab_separated

    def declared_columns(self) -> tuple[str, ...]:
        with self._open() as (header, _):
            return tuple(header)

    def rows(self) -> Iterator[Row]:
        with self._open() as (header, reader):
            for ordinal, cells in enumerate(reader, start=2):
                if self._tab_separated and len(cells) > len(header):
                    raise MergeError(
                        f"{self.path}:{ordinal}: {len(cells)} fields for {len(header)} columns; "
                        "a literal tab inside a TSV field is not allowed",
                        EXIT_SOURCE,
                    )
                yield Row(ordinal, self._mapping(header, cells))

    def _mapping(self, header: list[str], cells: list[str]) -> dict[str, str | None]:
        """Pair cells with their column, dropping extras and nulling empties."""
        return {
            name: None if self._dialect.is_null(text) else text for name, text in zip(header, cells)
        }

    @contextmanager
    def _open(self) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
        args = _TSV_READER_ARGS if self._tab_separated else self._dialect.csv_args()
        with open_text(self.path, self.spec.compression) as stream:
            reader = csv.reader(stream, **args)
            yield next(reader, []), reader


class JsonLinesSource(Source):
    """One flat JSON object per line; blank lines are ignored."""

    typed = True

    def rows(self) -> Iterator[Row]:
        with open_text(self.path, self.spec.compression) as stream:
            for ordinal, line in enumerate(stream, start=1):
                if line.strip():
                    yield Row(ordinal, self._object(line, f"{self.path}:{ordinal}"))

    def _object(self, line: str, location: str) -> dict[str, Any]:
        try:
            document = json.loads(line)
        except json.JSONDecodeError as error:
            raise MergeError(f"{location}: invalid JSON: {error.msg}", EXIT_SOURCE) from None
        if not isinstance(document, dict):
            raise MergeError(
                f"{location}: expected a JSON object, found {type(document).__name__}", EXIT_NESTED
            )
        return {name: _flat_value(name, value, location) for name, value in document.items()}


def _parquet_source(path: str, spec: FormatSpec, options: ReadOptions) -> Source:
    """Load the Parquet reader only once an input actually needs it.

    Importing pyarrow costs around 50 MB of resident memory, which a merge of
    text inputs alone should not have to pay out of ``--memory-limit-mb``.
    """
    from csvmerge.parquetio import ParquetSource

    return ParquetSource(path, spec, options.parquet_row_group_bytes)


_BUILDERS = {
    CSV: lambda path, spec, options: DelimitedSource(path, spec, options.dialect, tab_separated=False),
    TSV: lambda path, spec, options: DelimitedSource(path, spec, options.dialect, tab_separated=True),
    JSONL: lambda path, spec, options: JsonLinesSource(path, spec),
    PARQUET: _parquet_source,
}


def open_inputs(
    paths: list[str], input_format: str, compression: str, options: ReadOptions
) -> list[Source]:
    """Identify every input path and build the reader that suits it."""
    specs = [resolve_format(path, input_format, compression) for path in paths]
    return [_BUILDERS[spec.format](path, spec, options) for path, spec in zip(paths, specs)]


def _flat_value(name: str, value: Any, location: str) -> Any:
    """Reject a nested JSON value, and widen an integer too large for 64 bits."""
    if isinstance(value, (dict, list)):
        raise MergeError(
            f"{location}: column {name!r} holds a nested {type(value).__name__}; "
            "JSON Lines objects must be flat",
            EXIT_NESTED,
        )
    if type(value) is int and not _INT64_MIN <= value <= _INT64_MAX:
        return float(value)
    return value
