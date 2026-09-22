"""Reading a source file and reading the cursor's surroundings."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from . import imports
from .errors import SithError


@dataclass(frozen=True)
class CursorContext:
    """What the cursor is in the middle of typing.

    ``attribute`` records that the cursor sits after a dot even when
    ``receiver`` could not be parsed, so that a broken receiver yields no
    completions instead of falling back to plain name completion.  ``imports``
    is set instead when the cursor is inside an import statement, where the
    dots separate modules rather than attributes.
    """

    prefix: str
    attribute: bool
    receiver: ast.expr | None
    imports: imports.ImportContext | None = None


class SourceFile:
    """The text under analysis, addressable by 1-based line and 0-based column."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = [line.rstrip("\r") for line in text.split("\n")]

    @classmethod
    def load(cls, path: Path) -> "SourceFile":
        if not path.is_file():
            raise SithError(f"not a regular file: {path}")
        try:
            return cls(path.read_bytes().decode("utf-8"))
        except UnicodeDecodeError as error:
            raise SithError(f"not valid UTF-8: {path}") from error

    def offset(self, line: int, column: int) -> int:
        """The index into ``text`` of a 1-based line and 0-based column."""
        self.validate(line, column)
        preceding = self.text.split("\n")[:line - 1]
        return sum(len(text) + 1 for text in preceding) + column

    def validate(self, line: int, column: int) -> None:
        """Reject a position that the file does not have."""
        if not 1 <= line <= len(self.lines):
            raise SithError(f"line {line} is out of range (file has {len(self.lines)} lines)")
        text = self.lines[line - 1]
        if not 0 <= column <= len(text):
            raise SithError(
                f"column {column} is out of range (line {line} has {len(text)} characters)")

    def context_at(self, line: int, column: int) -> CursorContext:
        self.validate(line, column)
        before = self.lines[line - 1][:column]
        start = column
        while start and _is_name_character(before[start - 1]):
            start -= 1
        prefix, head = before[start:], before[:start]
        statement = imports.context(head)
        if statement is not None:
            return CursorContext(prefix, False, None, statement)
        head = head.rstrip()
        if not head.endswith("."):
            return CursorContext(prefix, False, None)
        return CursorContext(prefix, True, trailing_expression(head[:-1]))


def read(path: Path) -> str:
    """The text of a project file, undecodable bytes replaced rather than refused.

    A file only being read for the names it holds should never fail the request
    the way the file under the cursor does.
    """
    return path.read_text(encoding="utf-8", errors="replace")


def _is_name_character(character: str) -> bool:
    return character.isalnum() or character == "_"


def trailing_expression(text: str) -> ast.expr | None:
    """The longest suffix of ``text`` that is a complete expression.

    The cursor's line is rarely valid Python on its own, so the receiver of a
    dot is recovered by trimming from the left until what is left parses:
    ``print(os`` yields ``os``, ``x = [1, 2]`` yields the list literal.
    """
    for start in range(len(text)):
        chunk = text[start:].strip()
        if not chunk:
            continue
        try:
            return ast.parse(chunk, mode="eval").body
        except SyntaxError:
            continue
    return None
