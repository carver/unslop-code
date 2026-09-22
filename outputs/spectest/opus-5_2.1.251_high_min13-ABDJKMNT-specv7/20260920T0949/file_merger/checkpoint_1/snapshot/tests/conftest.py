"""Shared fixtures: run the CLI as a subprocess and build input fixtures on disk."""

import csv
import io
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "merge_files.py"


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def make_csv(workdir):
    """Write ``text`` (dedented) to ``name`` inside the work directory."""

    def _make(name, text):
        path = workdir / name
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def make_schema(workdir):
    """Write a schema JSON file from a list of (name, type) pairs."""

    def _make(name, columns):
        path = workdir / name
        payload = {"columns": [{"name": n, "type": t} for n, t in columns]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def run(workdir):
    """Invoke merge_files.py; by default assert it exited successfully."""

    def _run(*args, expect_ok=True):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *[str(a) for a in args]],
            capture_output=True,
            text=True,
            cwd=workdir,
        )
        if expect_ok:
            assert proc.returncode == 0, proc.stderr
        return proc

    return _run


def rows_of(text):
    """Parse CSV text into a list of rows."""
    return list(csv.reader(io.StringIO(text)))


def column(rows, name):
    """Return the values of ``name`` from parsed rows (header first)."""
    index = rows[0].index(name)
    return [row[index] for row in rows[1:]]
