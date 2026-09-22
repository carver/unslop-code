"""Reading delimited text inputs: the CSV and TSV dialects.

CSV follows RFC-4180 with the quote and escape characters the dialect flags
configure. TSV is the same reader with a tab delimiter and quoting switched
off, plus the two rules the spec states only for TSV: a header row is required
and a literal tab inside a field - visible as a surplus field - is rejected.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass

from .errors import SourceFormatError
from .records import Record, RecordStream


@dataclass(frozen=True)
class CsvFormat:
    """The CSV dialect plus the literal that stands for a null value."""

    quotechar: str = '"'
    escapechar: str | None = "\\"
    null_literal: str = ""

    def is_null(self, text: str | None) -> bool:
        """A cell is null when it is absent, empty, or equal to the null literal."""
        return text is None or text == "" or text == self.null_literal


@contextmanager
def open_delimited(spec, fmt: CsvFormat):
    """Yield the records of one CSV or TSV input."""
    is_tsv = spec.format == "tsv"
    with spec.open_text() as handle:
        reader = csv.reader(handle, **_dialect(fmt, is_tsv))
        header = next(reader, None)
        if header is None:
            if is_tsv:
                raise SourceFormatError(f"{spec.path}: TSV input has no header row")
            yield RecordStream((), iter(()))  # an empty CSV contributes nothing
        else:
            names = tuple(header)
            yield RecordStream(names, _records(spec, reader, names, fmt, is_tsv))


def _dialect(fmt: CsvFormat, is_tsv: bool) -> dict:
    """The csv module's settings for the dialect of one source kind."""
    if is_tsv:
        return {"delimiter": "\t", "quoting": csv.QUOTE_NONE, "quotechar": None}
    return {
        "delimiter": ",",
        "quotechar": fmt.quotechar,
        "escapechar": fmt.escapechar,
        "doublequote": True,
    }


def _records(spec, reader, header: tuple[str, ...], fmt: CsvFormat, is_tsv: bool):
    for row in reader:
        if not row:  # a blank line between records carries no data
            continue
        if is_tsv and len(row) > len(header):
            raise SourceFormatError(f"{spec.path}:{reader.line_num}: literal tab inside a field")
        yield Record(header, [None if fmt.is_null(text) else text for text in row], reader.line_num)
