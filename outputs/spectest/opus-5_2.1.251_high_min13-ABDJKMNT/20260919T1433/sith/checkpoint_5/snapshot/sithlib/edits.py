"""Editing files and reporting what a refactoring changed.

A refactoring is a set of :class:`Edit`s against the files it touches plus the
paths it moves. Both answers the subcommands offer are built from that pair:
a JSON map of new file contents, or the unified diff of the same change.
Nothing here writes to disk - the tool reports the change, it does not apply it.
"""

from __future__ import annotations

import ast
import difflib
import keyword
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .definitions import document
from .source import SourceError


class RefactorError(SourceError):
    """A refactoring the tool refuses to carry out."""


def checked_identifier(name: str) -> str:
    """The name a refactoring was asked for, if Python can spell it."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise RefactorError(f"not a valid Python identifier: {name}")
    return name


@dataclass(frozen=True)
class Edit:
    """A replacement of one span of one file.

    Lines are 1-based and columns 0-based, as everywhere else in the tool. An
    empty span inserts, and empty text deletes.
    """

    path: Path
    line: int
    column: int
    end_line: int
    end_column: int
    text: str


def rewrite(path: Path, line: int, column: int, old: str, new: str) -> Edit:
    """An edit replacing an identifier written at a position."""
    return Edit(path, line, column, line, column + len(old), new)


def insertion(path: Path, line: int, text: str) -> Edit:
    """An edit adding whole lines before the given line."""
    return Edit(path, line, 0, line, 0, text)


def line_span(path: Path, first: int, last: int, text: str) -> Edit:
    """An edit replacing whole lines, ``first`` to ``last`` inclusive."""
    return Edit(path, first, 0, last + 1, 0, text)


def applied(text: str, edits: Iterable[Edit]) -> str:
    """One file's text with its edits spliced in, last position first."""
    offsets = _line_offsets(text)
    result = text
    for edit in sorted(edits, key=_span, reverse=True):
        start = offsets[edit.line - 1] + edit.column
        end = offsets[edit.end_line - 1] + edit.end_column
        result = result[:start] + edit.text + result[end:]
    return result


def _span(edit: Edit) -> Tuple[int, int, int, int]:
    return edit.line, edit.column, edit.end_line, edit.end_column


def _line_offsets(text: str) -> List[int]:
    """Character offset each line of a text starts at, with one past the end."""
    offsets, position = [0], 0
    for line in text.split("\n"):
        position += len(line) + 1
        offsets.append(position)
    return offsets


def source_text(lines: Sequence[str], node: ast.AST) -> str:
    """The text a node occupies in the file it was parsed from."""
    if node.lineno == node.end_lineno:
        return lines[node.lineno - 1][node.col_offset:node.end_col_offset]
    first = lines[node.lineno - 1][node.col_offset:]
    last = lines[node.end_lineno - 1][:node.end_col_offset]
    return "\n".join([first, *lines[node.lineno:node.end_lineno - 1], last])


def indentation(lines: Sequence[str], line: int) -> str:
    """The leading whitespace of a line, as written."""
    text = lines[line - 1]
    return text[:len(text) - len(text.lstrip())]


class Refactoring:
    """The change a refactoring makes, in the two shapes it is reported in."""

    def __init__(self, root: Path, edits: Iterable[Edit], renames: Iterable = ()):
        self.root = root
        self.edits = set(edits)
        self.renames = list(renames)

    def report(self, diff: bool) -> str:
        """The answer written to standard output."""
        changed = self._changed_files()
        return self._diff(changed) if diff else self._document(changed)

    def _changed_files(self) -> List[Tuple[Path, str, str]]:
        """Each edited file with its old and new text; unchanged files drop out."""
        grouped: Dict[Path, List[Edit]] = {}
        for edit in self.edits:
            grouped.setdefault(edit.path, []).append(edit)
        changed = []
        for path in sorted(grouped):
            old = path.read_text(encoding="utf-8")
            new = applied(old, grouped[path])
            if new != old:
                changed.append((path, old, new))
        return changed

    def _document(self, changed: List[Tuple[Path, str, str]]) -> str:
        return document(
            changed_files={self._relative(path): new for path, _, new in changed},
            renames={self._relative(old): self._relative(new) for old, new in self.renames},
        )

    def _diff(self, changed: List[Tuple[Path, str, str]]) -> str:
        moves = "".join(
            f"rename from {self._relative(old)}\nrename to {self._relative(new)}\n"
            for old, new in self.renames
        )
        return moves + "".join(
            _file_diff(self._relative(path), old, new) for path, old, new in changed
        )

    def _relative(self, path: Path) -> str:
        """A path as the answer spells it: POSIX, relative to the project root."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def _file_diff(label: str, old: str, new: str) -> str:
    """The unified diff of one file, headed by its project-relative path."""
    return "".join(
        difflib.unified_diff(_terminated(old), _terminated(new), fromfile=label, tofile=label)
    )


def _terminated(text: str) -> List[str]:
    """A text as lines that keep their endings, the last one newline-terminated."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines
