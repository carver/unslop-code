"""Where a record came from: what error messages quote, and how its cells arrive."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Origin:
    """One record's provenance.

    `delimited` marks sources whose cells are plain text, which is what decides
    whether a nested column's value still has to be parsed as a JSON literal.
    """

    file: str
    line: int
    delimited: bool = False

    def __str__(self):
        return f"file={self.file} line={self.line}"
