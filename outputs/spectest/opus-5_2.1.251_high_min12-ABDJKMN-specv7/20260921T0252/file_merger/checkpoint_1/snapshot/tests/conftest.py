"""Shared helpers for the merge_files.py spec tests."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "merge_files.py"
PYTHON = sys.executable


class Result(object):
    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def ok(self):
        return self.returncode == 0

    def rows(self):
        """Parse stdout as the tool's deterministic output dialect."""
        return parse_csv(self.stdout)


def run_tool(*args, **kwargs):
    """Invoke the CLI as a subprocess; stdout/stderr are fully drained."""
    cwd = kwargs.pop("cwd", None)
    timeout = kwargs.pop("timeout", 300)
    argv = [PYTHON, str(TOOL)] + [str(a) for a in args]
    proc = subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
    )
    return Result(proc)


def parse_csv(text):
    """Minimal RFC-4180 reader (doubled quotes only) for output checking."""
    rows = []
    field = []
    row = []
    in_quotes = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            field.append(ch)
            i += 1
            continue
        if ch == '"' and not field:
            in_quotes = True
            i += 1
            continue
        if ch == ",":
            row.append("".join(field))
            field = []
            i += 1
            continue
        if ch == "\n":
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
            i += 1
            continue
        field.append(ch)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows


def write_file(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return str(path)


def write_csv(path, lines):
    """Write raw CSV lines (already formatted) joined with \\n."""
    return write_file(path, "\n".join(lines) + "\n")


def write_schema(path, columns):
    """columns: list of (name, type) tuples."""
    doc = {"columns": [{"name": n, "type": t} for n, t in columns]}
    return write_file(path, json.dumps(doc))


def col(rows, name):
    """Extract one named column from parsed rows (header + data)."""
    idx = rows[0].index(name)
    return [r[idx] for r in rows[1:]]


def body(rows):
    return rows[1:]


@pytest.fixture
def tmpdir_path(tmp_path):
    return tmp_path


@pytest.fixture
def merge(tmp_path):
    """Run the tool with --output - and return the Result."""
    def _merge(*args, **kwargs):
        return run_tool(*args, **kwargs)
    return _merge
