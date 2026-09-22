"""Shared helpers for the merge_files.py spec tests.

Every test drives the real CLI as a subprocess, because the spec is written
entirely in terms of the command line contract:

    python merge_files.py --output <PATH|-> --key <col>[,<col>...] ... <INPUT1.csv> ...
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "merge_files.py"


class Result:
    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def ok(self):
        return self.returncode == 0

    def __repr__(self):
        return f"Result(rc={self.returncode}, stdout={self.stdout!r}, stderr={self.stderr!r})"


def run(*args, cwd=None, timeout=300):
    """Run merge_files.py with the given argv tail."""
    argv = [sys.executable, str(SCRIPT)] + [str(a) for a in args]
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return Result(proc)


def run_ok(*args, **kw):
    res = run(*args, **kw)
    assert res.ok, f"expected success, got {res!r}"
    return res


def write(path, text):
    """Write an exact byte-for-byte UTF-8 file (LF endings, no translation)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return str(p)


def write_schema(path, columns):
    """columns: list of (name, type) pairs."""
    doc = {"columns": [{"name": n, "type": t} for n, t in columns]}
    return write(path, json.dumps(doc))


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def lines(text):
    """Split CSV output text into its physical lines (no trailing empty)."""
    assert "\r" not in text, f"output must use \\n line endings only: {text!r}"
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return text.split("\n")


def header(text):
    return lines(text)[0].split(",")


def body(text):
    return lines(text)[1:]


def col(text, name, quotechar='"'):
    """Return the values of one column, in output order, as raw CSV text fields."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text), quotechar=quotechar))
    idx = rows[0].index(name)
    return [r[idx] for r in rows[1:]]


def rows_of(text):
    """Parse output into a list of dicts using the default output dialect."""
    import csv
    import io

    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    head = all_rows[0]
    return [dict(zip(head, r)) for r in all_rows[1:]]


@pytest.fixture
def ws(tmp_path):
    """A scratch directory for input/output files."""
    return tmp_path
