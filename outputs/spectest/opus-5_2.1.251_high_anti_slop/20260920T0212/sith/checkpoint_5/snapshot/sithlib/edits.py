"""The text a refactoring rewrites: its edits, its result and its output."""

import difflib
from dataclasses import dataclass, field

from .source import read_source


@dataclass(frozen=True)
class Edit:
    """A span of one file replaced by new text, in 1-based lines and 0-based columns.

    A span of zero width inserts text, and empty text deletes the span. A whole
    line is removed by spanning from its start to the start of the line below.
    """

    path: str
    line: int
    column: int
    until_line: int
    until_column: int
    text: str


@dataclass(frozen=True)
class Changes:
    """What a refactoring produced: rewritten files and renamed paths.

    `files` maps a path relative to the project root to the ``(before, after)``
    pair of its contents, and `renames` maps an old relative path to the new
    one. A file that is both rewritten and renamed is keyed by its old path.
    """

    files: dict
    renames: dict = field(default_factory=dict)


def collect(project, edits, renames=None):
    """Apply the edits file by file, keeping the files whose text really changed."""
    grouped = {}
    for edit in dict.fromkeys(edits):
        grouped.setdefault(edit.path, []).append(edit)
    files = {}
    for path, group in grouped.items():
        before = read_source(path)
        after = apply_edits(before, group)
        if after != before:
            files[project.relative(path)] = (before, after)
    return Changes(files, renames or {})


def apply_edits(source, edits):
    """`source` with every edit applied, working backwards so offsets stay valid."""
    starts = _line_starts(source)
    text = source
    for edit in sorted(edits, key=lambda edit: (edit.line, edit.column), reverse=True):
        start = starts[edit.line - 1] + edit.column
        end = starts[edit.until_line - 1] + edit.until_column
        text = text[:start] + edit.text + text[end:]
    return text


def rendered(changes, diff):
    """The unified diff or the JSON object a refactoring command prints."""
    if diff:
        return as_diff(changes)
    return {
        "changed_files": {path: after for path, (_, after) in sorted(changes.files.items())},
        "renames": changes.renames,
    }


def as_diff(changes):
    """A unified diff per rewritten file, headed by a line pair per renamed path."""
    parts = [f"rename from {old}\nrename to {new}\n"
             for old, new in sorted(changes.renames.items())]
    for path, (before, after) in sorted(changes.files.items()):
        parts.extend(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            f"a/{path}",
            f"b/{changes.renames.get(path, path)}",
        ))
    return "".join(parts)


def _line_starts(source):
    """The offset each line starts at, plus the offset just past the last one."""
    offsets, position = [], 0
    for line in source.splitlines(keepends=True):
        offsets.append(position)
        position += len(line)
    return offsets + [position]
