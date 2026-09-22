"""The text edits a refactoring makes, and the two shapes it reports them in.

A refactoring never touches the filesystem: it collects the edits it would
make and answers with either the whole new text of each file it changed, or a
unified diff of the same thing.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field

from . import paths
from .source import read

Position = tuple[int, int]


@dataclass
class Buffer:
    """One file's text, with the edits queued against it.

    Every position is given against the *original* text, so edits are applied
    from the end of the file backwards.  Two edits that start in the same place
    are applied in the order they were queued, which lets a caller queue the
    replacement of a region and then an insertion in front of it.
    """

    path: str
    original: str
    edits: list[tuple[int, int, str]] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        """The original text split so that joining it back is loss-free."""
        return self.original.split("\n")

    @property
    def text(self) -> str:
        """The file as the refactoring leaves it."""
        result = self.original
        for start, end, text in sorted(self.edits, key=lambda edit: edit[0], reverse=True):
            result = result[:start] + text + result[end:]
        return result

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def replace(self, start: Position, end: Position, text: str) -> None:
        """Put `text` where the source from `start` up to (not including) `end` stands."""
        self.edits.append((self.offset(*start), self.offset(*end), text))

    def insert_lines(self, before: int, added: list[str]) -> None:
        """Put whole lines in front of the 1-based line `before`."""
        at = self.offset(before, 0)
        self.edits.append((at, at, "".join(line + "\n" for line in added)))

    def replace_lines(self, first: int, last: int, added: list[str]) -> None:
        """Put whole lines where lines `first` to `last`, inclusive, stand."""
        self.replace((first, 0), (last + 1, 0), "".join(line + "\n" for line in added))

    def offset(self, line: int, column: int) -> int:
        """The character index of a 1-based line and 0-based column."""
        lines = self.lines
        if line > len(lines):
            return len(self.original)
        return sum(len(text) + 1 for text in lines[: line - 1]) + column

    def diff(self) -> str:
        """The change to this file as a unified diff, empty when nothing changed."""
        hunks = difflib.unified_diff(
            self.original.splitlines(), self.text.splitlines(),
            fromfile=self.path, tofile=self.path, lineterm="",
        )
        return "".join(line + "\n" for line in hunks)


class Workspace:
    """Every file one refactoring rewrites, and the answer it turns into."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.buffers: dict[str, Buffer] = {}
        self.renames: dict[str, str] = {}

    def buffer(self, path: str) -> Buffer:
        """The buffer for a path relative to the project root, read from disk once."""
        if path not in self.buffers:
            self.buffers[path] = Buffer(path, read(os.path.join(self.root, path)))
        return self.buffers[path]

    def buffer_for(self, path: str) -> Buffer:
        """The buffer for a path as the caller wrote it on the command line."""
        return self.buffer(paths.relative(os.path.abspath(path), self.root))

    def rename_path(self, old: str, new: str) -> None:
        """Record that a file or directory moves, which no text edit can express."""
        self.renames[old] = new

    @property
    def changed(self) -> list[Buffer]:
        """The buffers whose text the refactoring actually altered, by path."""
        return [buffer for _, buffer in sorted(self.buffers.items()) if buffer.changed]

    def answer(self, diff: bool) -> dict | str:
        """The payload of the command: a diff when asked for one, JSON otherwise."""
        if diff:
            return self._diff()
        return {
            "changed_files": {buffer.path: buffer.text for buffer in self.changed},
            "renames": self.renames,
        }

    def _diff(self) -> str:
        moves = [f"rename from {old}\nrename to {new}\n" for old, new in self.renames.items()]
        return "".join(moves) + "".join(buffer.diff() for buffer in self.changed)
