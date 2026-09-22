"""Reading source files and parsing them tolerantly.

Half-written code is the normal case for a completion tool, so a file that
the parser rejects is repaired line by line rather than abandoned.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List

MAX_REPAIRS = 40
INDENT_WIDTH = 4


class SourceError(Exception):
    """A file or cursor position that cannot be analysed."""


@dataclass
class Source:
    """A loaded source file, split into lines and parsed."""

    path: Path
    lines: List[str]
    tree: ast.Module

    @classmethod
    def load(cls, location) -> "Source":
        path = Path(location)
        if not path.is_file():
            raise SourceError(f"not a regular file: {path}")
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceError(f"not valid UTF-8: {path}") from error
        return cls(path, text.split("\n"), parse_tolerant(text))

    def line_at(self, line: int, col: int) -> str:
        """The text of a line, after checking the position lies inside it."""
        if line < 1 or line > len(self.lines):
            raise SourceError(f"line {line} is out of range (file has {len(self.lines)} lines)")
        text = self.lines[line - 1]
        if col < 0 or col > len(text):
            raise SourceError(f"column {col} is out of range (line has {len(text)} characters)")
        return text


def parse_tolerant(text: str) -> ast.Module:
    """Parse ``text``, neutralising the lines the parser rejects.

    Line numbers of the surviving code are preserved: rejected lines are
    replaced in place, never removed.
    """
    lines = text.split("\n")
    attempts: Counter = Counter()
    for _ in range(MAX_REPAIRS):
        try:
            return ast.parse("\n".join(lines))
        except SyntaxError as error:
            index = (error.lineno or 1) - 1
            if not 0 <= index < len(lines) or attempts[index] > 1:
                break
            lines[index] = _repaired(lines, index, error.msg or "", attempts[index])
            attempts[index] += 1
    return ast.Module(body=[], type_ignores=[])


def _repaired(lines: List[str], index: int, message: str, attempt: int) -> str:
    """A replacement for a rejected line.

    The first attempt keeps the block structure by standing in for the line
    with ``pass``; a line that is still rejected is dropped entirely.
    """
    if attempt:
        return ""
    if "expected an indented block" in message:
        return " " * (_enclosing_indent(lines, index) + INDENT_WIDTH) + "pass"
    return " " * indent_of(lines[index]) + "pass"


def _enclosing_indent(lines: List[str], index: int) -> int:
    """Indentation of the last non-blank line before ``index``."""
    for line in reversed(lines[:index]):
        if line.strip():
            return indent_of(line)
    return 0


def indent_of(line: str) -> int:
    """Number of leading whitespace characters on a line."""
    return len(line) - len(line.lstrip())
