"""CSV and TSV sources: header-aligned records from a delimited text file."""

from __future__ import annotations

from ..errors import InputError
from .detect import open_text


class DelimitedSource:
    """Shared machinery for the two delimited text formats.

    Subclasses supply the row splitting and whatever dialect rules can only be
    checked row by row; everything else — the header, aligning short rows, the
    origin string used in error messages — is common.
    """

    #: Precedence of this source's type information (AMBIGUITIES T19).
    tier = 1

    def __init__(self, path, compression):
        self.path = path
        self._compression = compression

    def fields(self):
        """The column names declared by the header row."""
        with self._open() as stream:
            return tuple(self._header(self._rows(stream)) or ())

    def records(self):
        """Yield ``(origin, {column: text or None})`` for each data row."""
        with self._open() as stream:
            rows = self._rows(stream)
            header = self._header(rows)
            if header is None:
                return
            for number, row in enumerate(rows, start=2):
                self._check(header, row, number)
                yield f"{self.path}:{number}", _align(header, row)

    def _open(self):
        return open_text(self.path, self._compression, newline=self.newline)

    def _header(self, rows):
        return next(rows, None)

    def _check(self, header, row, number):
        """Hook for dialect rules only visible one row at a time."""


class CsvSource(DelimitedSource):
    """RFC-4180 CSV, quoted as the `--csv-*` flags describe."""

    #: The `csv` module requires untranslated line endings.
    newline = ""

    def __init__(self, path, compression, dialect):
        super().__init__(path, compression)
        self._dialect = dialect

    def _rows(self, stream):
        return self._dialect.reader(stream)


class TsvSource(DelimitedSource):
    """Tab-delimited text with no quoting.

    A literal tab inside a field is indistinguishable from a delimiter, so it shows
    up as a row with more fields than the header (AMBIGUITIES T25).
    """

    newline = "\n"

    def _rows(self, stream):
        return (line.rstrip("\n").split("\t") for line in stream)

    def _header(self, rows):
        header = next(rows, None)
        if header is None:
            raise InputError(f"{self.path}: TSV input has no header row")
        return header

    def _check(self, header, row, number):
        if len(row) > len(header):
            raise InputError(f"{self.path}:{number}: literal tab inside a field")


def _align(header, row):
    """Pair header names with cells, blanks and absent trailing cells becoming null.

    Duplicate header names keep their first occurrence (AMBIGUITIES T16).
    """
    record = {}
    for name, text in zip(header, row):
        record.setdefault(name, text or None)
    for name in header[len(row):]:
        record.setdefault(name, None)
    return record
