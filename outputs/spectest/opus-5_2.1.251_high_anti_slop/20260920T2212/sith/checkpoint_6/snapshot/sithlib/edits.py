"""The edits a refactoring makes and the two ways of reporting them.

Every refactoring works the same way: it decides on a list of :class:`Edit`s --
one replacement of one span of one file -- and hands them here to be applied.
The result is reported either as the whole text of every file that changed or
as a unified diff of the same changes.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .trees import Span


@dataclass(frozen=True)
class Edit:
    """Replacing the text of one span of the file at ``path``.

    ``path`` is relative to the project root.  Two passes of a refactoring that
    reach the same conclusion -- renaming an import and renaming the name it
    binds, say -- produce equal edits, which are applied once.
    """

    path: str
    span: Span
    replacement: str


@dataclass(frozen=True)
class FileChange:
    """One file before and after, and the path it ends up at."""

    path: str
    old: str
    new: str
    destination: str

    @property
    def rewritten(self) -> bool:
        return self.new != self.old


@dataclass(frozen=True)
class Refactoring:
    """What a refactoring did: the files it rewrote and the paths it moved."""

    changes: list[FileChange]
    renames: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """The rewritten files by the path they end up at, and the moves made."""
        return {"changed_files": {change.destination: change.new
                                  for change in self.changes if change.rewritten},
                "renames": self.renames}

    def diff(self) -> str:
        """The same changes as a unified diff, one section per file.

        A file that only moved has no hunks, so its section is the two header
        lines naming where it came from and where it went.
        """
        return "".join(_section(change) for change in self.changes)


def collect(edits: Iterable[Edit], texts: Mapping[str, str],
            renames: Mapping[str, str] | None = None) -> Refactoring:
    """Apply ``edits`` to the texts they name, moving what ``renames`` moves.

    ``texts`` holds every file the refactoring looked at, keyed by its path
    relative to the project root; only the ones an edit or a move touches end
    up in the result.
    """
    moves = dict(renames or {})
    grouped: dict[str, list[Edit]] = {}
    for edit in dict.fromkeys(edits):
        grouped.setdefault(edit.path, []).append(edit)
    touched = set(grouped) | {path for path in texts if destination(path, moves) != path}
    return Refactoring([FileChange(path, texts[path], apply(texts[path], grouped.get(path, ())),
                                   destination(path, moves))
                        for path in sorted(touched)], moves)


def apply(text: str, edits: Iterable[Edit]) -> str:
    """``text`` with every edit applied, the last first so the earlier ones hold."""
    starts = _line_starts(text)
    spans = sorted(((starts[edit.span.line - 1] + edit.span.column,
                     starts[edit.span.end_line - 1] + edit.span.end_column, edit.replacement)
                    for edit in edits), reverse=True)
    for start, end, replacement in spans:
        text = text[:start] + replacement + text[end:]
    return text


def destination(path: str, renames: Mapping[str, str]) -> str:
    """Where ``path`` lands once the renamed files and directories have moved."""
    for old, new in renames.items():
        if path == old:
            return new
        if path.startswith(f"{old}/"):
            return f"{new}/{path[len(old) + 1:]}"
    return path


def _section(change: FileChange) -> str:
    body = difflib.unified_diff(change.old.splitlines(keepends=True),
                                change.new.splitlines(keepends=True))
    return f"--- a/{change.path}\n+++ b/{change.destination}\n" + "".join(list(body)[2:])


def _line_starts(text: str) -> list[int]:
    """The offset each line begins at, so a position can be turned into one."""
    offsets, position = [0], 0
    for line in text.split("\n")[:-1]:
        position += len(line) + 1
        offsets.append(position)
    return offsets
