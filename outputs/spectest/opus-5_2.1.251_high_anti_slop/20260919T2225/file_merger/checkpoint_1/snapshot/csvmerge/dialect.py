"""The single CSV dialect used for both reading inputs and writing the output."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO


@dataclass(frozen=True)
class CsvDialect:
    """Comma-delimited, ``\\n``-terminated RFC-4180 dialect with overridable quoting.

    ``escapechar`` of ``None`` keeps the RFC default of escaping a quote by
    doubling it; supplying one switches to backslash-style escaping instead.
    ``null_literal`` is the text written for missing values, and is recognised
    as a null on input as well so output can be fed back in.
    """

    quotechar: str = '"'
    escapechar: str | None = None
    null_literal: str = ""

    def reader(self, stream: IO[str]) -> Iterator[list[str]]:
        return csv.reader(stream, **self._parameters())

    def writer(self, stream: IO[str]):
        return csv.writer(stream, quoting=csv.QUOTE_MINIMAL, **self._parameters())

    def is_null(self, text: str) -> bool:
        """Report whether an input cell should be read as a missing value."""
        return text == "" or text == self.null_literal

    def _parameters(self) -> dict:
        return {
            "delimiter": ",",
            "quotechar": self.quotechar,
            "doublequote": self.escapechar is None,
            "escapechar": self.escapechar,
            "lineterminator": "\n",
        }
