"""The CSV dialect shared by the CSV reader and the output writer.

Checkpoint 2 states that the output uses "configured CSV dialect flags for output
quoting/escaping", so one dialect object serves both directions (AMBIGUITIES T7).
TSV is defined as having no quoting at all and therefore ignores it (T31).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class CsvDialect:
    """The `--csv-quotechar` / `--csv-escapechar` pair.

    With no escape character, a quote inside a quoted field is escaped by doubling,
    which is what RFC-4180 prescribes.
    """

    quotechar: str = '"'
    escapechar: str | None = None

    def reader(self, stream):
        return csv.reader(stream, **self._settings())

    def writer(self, stream):
        return csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_MINIMAL, **self._settings())

    def _settings(self):
        return {
            "delimiter": ",",
            "quotechar": self.quotechar,
            "doublequote": self.escapechar is None,
            "escapechar": self.escapechar,
        }
