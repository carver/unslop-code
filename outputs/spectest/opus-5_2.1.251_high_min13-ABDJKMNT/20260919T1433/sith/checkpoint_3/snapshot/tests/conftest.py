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
    def definitions(self):
        return self.data["definitions"]

    @property
    def only(self):
        """The single definition of an unambiguous answer."""
        definitions = self.definitions
        assert len(definitions) == 1, definitions
        return definitions[0]

    @property
    def names(self):
        return [item["name"] for item in self.items]

    def by_name(self, name):
        return next(item for item in self.items if item["name"] == name)


def write_files(root, files):
    """Write a mapping of relative paths to sources, making directories."""
    for name, text in (files or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def invoke(command, path, line, col, *, flags=(), project=None):
    """Invoke one CLI subcommand on an existing file at the given position."""
    argv = [sys.executable, str(SITH), command, str(path), str(line), str(col), *flags]
    if project is not None:
        argv += ["--project", str(project)]
    return Result(subprocess.run(argv, capture_output=True, text=True))


def run(path, line, col, *, fuzzy=False, project=None):
    """Invoke `complete` on an existing file at the given position."""
    return invoke("complete", path, line, col, flags=["--fuzzy"] if fuzzy else [], project=project)


@pytest.fixture
def complete(tmp_path):
    """Write a ``$``-marked source to disk and complete at the marker."""

    def _complete(source, *, fuzzy=False, name="module_under_test.py", extra=None, project=None):
        write_files(tmp_path, extra)
        text, line, col = split_cursor(source)
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return run(path, line, col, fuzzy=fuzzy, project=_root(tmp_path, project))

    return _complete


def _root(tmp_path, project):
    """The ``--project`` argument for a root written relative to ``tmp_path``."""
    return None if project is None else tmp_path / project


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


def run_query(command, path, line, col, *, follow=False, project=None):
    """Invoke `infer` or `goto` on an existing file at the given position."""
    flags = ["--follow-imports"] if follow else []
    return invoke(command, path, line, col, flags=flags, project=project)


def _query_fixture(command, tmp_path):
    """Build a fixture that runs ``command`` at a ``$``-marked cursor."""

    def _query(source, *, name="module_under_test.py", extra=None, project=None, follow=False):
        write_files(tmp_path, extra)
        text, line, col = split_cursor(source)
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return run_query(command, path, line, col, follow=follow, project=_root(tmp_path, project))

    return _query


@pytest.fixture
def infer(tmp_path):
    """Write a ``$``-marked source to disk and infer at the marker."""
    return _query_fixture("infer", tmp_path)


@pytest.fixture
def goto(tmp_path):
    """Write a ``$``-marked source to disk and goto at the marker."""
    return _query_fixture("goto", tmp_path)
