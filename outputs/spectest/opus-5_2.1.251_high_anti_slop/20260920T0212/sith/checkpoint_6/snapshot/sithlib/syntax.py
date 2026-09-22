"""The `errors` command: the syntax errors a file holds."""

import ast

from .source import read_source


def syntax_errors(path):
    """The records for what Python rejects in a file, and nothing when it parses.

    The parser stops at its first complaint, so a broken file reports the one
    error that keeps it from parsing.
    """
    try:
        ast.parse(read_source(path), filename=path)
    except SyntaxError as error:
        return [_record(error)]
    return []


def _record(error):
    """One syntax error as the JSON object the command prints."""
    line = error.lineno or 1
    column = error.offset or 1
    return {
        "line": line,
        "column": column - 1,
        "until_line": error.end_lineno or line,
        "until_column": (error.end_offset or column) - 1,
        "message": error.msg,
    }
