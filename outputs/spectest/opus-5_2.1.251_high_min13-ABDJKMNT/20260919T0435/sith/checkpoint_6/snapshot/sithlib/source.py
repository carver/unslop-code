"""Loading a source file and parsing it in the face of syntax errors."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass

MAX_REPAIRS = 200


class SithError(Exception):
    """A condition that makes the request unanswerable; reported on STDERR."""


def read(path: str) -> str:
    """The text of a source file, with every way of failing reported alike."""
    if not os.path.isfile(path):
        raise SithError(f"not a regular file: {path}")
    try:
        data = open(path, "rb").read()
    except OSError as exc:
        raise SithError(f"cannot read {path}: {exc}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SithError(f"not valid UTF-8: {path}") from exc


@dataclass
class SourceFile:
    """The text of the file under the cursor, split into physical lines."""

    path: str
    lines: list[str]

    @classmethod
    def load(cls, path: str) -> "SourceFile":
        # An empty buffer still has one addressable (empty) line.
        return cls(path, read(path).splitlines() or [""])

    def validate(self, line: int, col: int) -> None:
        """Raise if the 1-based line / 0-based column is outside the file."""
        if not 1 <= line <= len(self.lines):
            raise SithError(f"line {line} out of range (file has {len(self.lines)} lines)")
        width = len(self.lines[line - 1])
        if not 0 <= col <= width:
            raise SithError(f"column {col} out of range (line {line} has {width} characters)")


def parse_tolerant(lines: list[str], cursor_line: int | None = None) -> ast.Module:
    """Parse `lines`, neutralising whatever cannot be parsed.

    A buffer being edited is routinely mid-statement, so a SyntaxError is the
    expected case rather than an exceptional one.  Offending lines are replaced
    with an indentation-preserving `pass` so that the block structure around
    them survives, and parsing is retried.

    A cursor resting on a blank line is stubbed up front, because an empty
    block body is reported against some *other* line -- usually the next
    statement, which is innocent and still holds bindings worth keeping.
    """
    tree, _ = _try_parse(lines)
    if tree is not None:
        return tree

    working = list(lines)
    if cursor_line is not None and not working[cursor_line - 1].strip():
        working[cursor_line - 1] = _stub(working[cursor_line - 1])

    for _ in range(MAX_REPAIRS):
        tree, error = _try_parse(working)
        if tree is not None:
            return tree
        index = _error_index(error, working)
        if index is None:
            break
        working[index] = _neutralize(working[index])

    return _parse_blockwise(lines)


def _try_parse(lines: list[str]) -> tuple[ast.Module | None, SyntaxError | None]:
    try:
        return ast.parse("\n".join(lines)), None
    except SyntaxError as exc:
        return None, exc
    except ValueError:
        # Source containing a NUL byte: valid UTF-8, but not compilable.
        return None, None


def _error_index(error: SyntaxError | None, lines: list[str]) -> int | None:
    """Index of the line to neutralise next, or None when no progress is possible."""
    if error is None or error.lineno is None:
        return None
    index = min(error.lineno, len(lines)) - 1
    if index < 0 or not lines[index].strip():
        return None
    return index


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _stub(line: str) -> str:
    """Replace a line's content with `pass`, keeping its indentation."""
    return _indent(line) + "pass"


def _neutralize(line: str) -> str:
    """Blank a line, or stub it when stubbing actually changes something."""
    stub = _stub(line)
    return "" if stub == line else stub


def _parse_blockwise(lines: list[str]) -> ast.Module:
    """Last resort: keep the top-level blocks that parse on their own."""
    module = ast.Module(body=[], type_ignores=[])
    for start, block in _top_level_blocks(lines):
        tree, _ = _try_parse(block)
        if tree is None:
            continue
        ast.increment_lineno(tree, start)
        module.body.extend(tree.body)
    return module


def _top_level_blocks(lines: list[str]):
    """Yield (offset, block-lines) for each unindented statement and its body."""
    start = 0
    for index, line in enumerate(lines):
        if index > start and line.strip() and not line[0].isspace():
            yield start, lines[start:index]
            start = index
    if start < len(lines):
        yield start, lines[start:]
