"""The syntax errors a file holds, as the ``errors`` command reports them."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .parsing import syntax_errors


@dataclass(frozen=True)
class Diagnostic:
    """One rejected region: 1-based lines, 0-based columns, and what the parser said."""

    line: int
    column: int
    until_line: int
    until_column: int
    message: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def diagnose(text: str) -> list[Diagnostic]:
    """Every syntax error ``text`` holds, in the order the lines are written."""
    found = [_reported(error) for error in syntax_errors(text)]
    return sorted(found, key=lambda entry: (entry.line, entry.column))


def _reported(error: SyntaxError) -> Diagnostic:
    """A parser error as a diagnostic; its columns are 1-based and ours are not."""
    line = error.lineno or 1
    column = max((error.offset or 1) - 1, 0)
    end_column = max((error.end_offset or error.offset or 1) - 1, 0)
    return Diagnostic(line, column, error.end_lineno or line, end_column, error.msg)
