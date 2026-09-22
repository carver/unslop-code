"""Shared helpers for driving the `sith.py` command line."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SITH = Path(__file__).resolve().parent.parent / "sith.py"
CURSOR = "$"


def split_cursor(source):
    """Return (source without the ``$`` marker, line, col) for a marked source."""
    index = source.index(CURSOR)
    before = source[:index]
    line = before.count("\n") + 1
    col = len(before) - (before.rfind("\n") + 1)
    return source.replace(CURSOR, "", 1), line, col


class Result:
    """The outcome of one `sith.py complete` invocation."""

    def __init__(self, process):
        self.process = process

    @property
    def code(self):
        return self.process.returncode

    @property
    def stdout(self):
        return self.process.stdout

    @property
    def stderr(self):
        return self.process.stderr

    @property
    def data(self):
        return json.loads(self.process.stdout)

    @property
    def items(self):
        return self.data["completions"]

    @property
    def names(self):
        return [item["name"] for item in self.items]

    def by_name(self, name):
        return next(item for item in self.items if item["name"] == name)


def run(path, line, col, *, fuzzy=False):
    """Invoke the CLI on an existing file at the given position."""
    command = [sys.executable, str(SITH), "complete", str(path), str(line), str(col)]
    if fuzzy:
        command.append("--fuzzy")
    return Result(subprocess.run(command, capture_output=True, text=True))


@pytest.fixture
def complete(tmp_path):
    """Write a ``$``-marked source to disk and complete at the marker."""

    def _complete(source, *, fuzzy=False, name="module_under_test.py", extra=None):
        for other_name, other_source in (extra or {}).items():
            (tmp_path / other_name).write_text(other_source, encoding="utf-8")
        text, line, col = split_cursor(source)
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return run(path, line, col, fuzzy=fuzzy)

    return _complete


@pytest.fixture
def write(tmp_path):
    """Write a source file verbatim (no cursor marker) and return its path."""

    def _write(text, name="module_under_test.py", encoding="utf-8"):
        path = tmp_path / name
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding=encoding)
        return path

    return _write
