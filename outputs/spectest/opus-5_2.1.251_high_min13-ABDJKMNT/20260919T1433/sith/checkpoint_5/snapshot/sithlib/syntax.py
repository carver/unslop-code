"""The `errors` subcommand.

Reporting syntax errors is the one command that wants the parser's complaints
rather than the tolerant parse the rest of the tool runs on, so the file is
parsed again here, strictly.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass

from .definitions import document
from .source import Source


@dataclass(frozen=True)
class SyntaxReport:
    """One syntax error, spanning from a start position to an end position."""

    line: int
    column: int
    until_line: int
    until_column: int
    message: str


def syntax_errors(source: Source) -> str:
    """The syntax errors of a file, as a JSON document.

    The parser stops at the first error it cannot get past, so the answer
    holds that error alone; a file it accepts reports none.
    """
    try:
        ast.parse(source.text)
    except SyntaxError as error:
        return document(errors=[asdict(_reported(error))])
    return document(errors=[])


def _reported(error: SyntaxError) -> SyntaxReport:
    """A parser error as the record the command reports.

    The parser counts columns from one and leaves the end of an error open
    where it cannot tell how far the problem reaches; both are normalised to
    the tool's own 0-based columns.
    """
    line = error.lineno or 1
    column = max((error.offset or 1) - 1, 0)
    until_line = error.end_lineno or line
    end = (error.end_offset or 0) - 1
    return SyntaxReport(line, column, until_line, max(end, column), error.msg or "invalid syntax")
