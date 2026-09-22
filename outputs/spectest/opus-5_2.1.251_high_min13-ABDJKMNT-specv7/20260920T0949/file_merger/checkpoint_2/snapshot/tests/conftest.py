"""Shared fixtures: run the CLI as a subprocess and build input fixtures on disk."""

import csv
import gzip
import io
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
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


@pytest.fixture
def make_text(workdir):
    """Write ``text`` verbatim to ``name`` inside the work directory."""

    def _make(name, text):
        path = workdir / name
        path.write_text(text, encoding="utf-8")
        return path

    return _make


@pytest.fixture
def make_jsonl(workdir):
    """Write one JSON object per line, from a list of dicts."""

    def _make(name, records):
        path = workdir / name
        body = "".join(json.dumps(record) + "\n" for record in records)
        path.write_text(body, encoding="utf-8")
        return path

    return _make


@pytest.fixture
def make_parquet(workdir):
    """Write a parquet file from a dict of column name to pyarrow array/list."""

    def _make(name, columns, schema=None):
        path = workdir / name
        table = pa.table(columns, schema=schema)
        pq.write_table(table, path)
        return path

    return _make


@pytest.fixture
def gzipped(workdir):
    """Gzip an existing file into ``<name>.gz`` and drop the original."""

    def _make(path, name=None):
        source = Path(path)
        target = workdir / (name or source.name + ".gz")
        with gzip.open(target, "wb") as handle:
            handle.write(source.read_bytes())
        source.unlink()
        return target

    return _make
