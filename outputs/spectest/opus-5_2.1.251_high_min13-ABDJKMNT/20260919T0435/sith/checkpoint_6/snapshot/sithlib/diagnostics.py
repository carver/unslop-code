"""The `errors` command: what the parser refuses to read, as data.

A file that will not parse is an answer rather than a failure, so the errors
are reported in the payload and the exit status stays 0.
"""

from __future__ import annotations

import ast

from .source import read


def errors(path: str) -> list[dict]:
    """The syntax errors of one file.

    The parser stops at the first thing it cannot read, so at most one error
    is ever reported: whatever follows a broken statement cannot be trusted to
    be broken in its own right.
    """
    try:
        ast.parse(read(path))
    except SyntaxError as error:
        return [_reported(error)]
    return []


def _reported(error: SyntaxError) -> dict:
    """One parser complaint, with its 1-based lines and 0-based columns."""
    line = error.lineno or 1
    column = _column(error.offset)
    return {
        "line": line,
        "column": column,
        "until_line": error.end_lineno or line,
        "until_column": _column(error.end_offset) if error.end_offset else column,
        "message": error.msg,
    }


def _column(offset: int | None) -> int:
    """A parser column, which counts from one, as a column that counts from zero."""
    return max((offset or 1) - 1, 0)
