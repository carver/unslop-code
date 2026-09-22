"""Shared helpers: every test drives the real CLI the way the spec documents it."""

import csv
import gzip
import io
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "merge_files.py"


class CliResult:
    """Outcome of one `python merge_files.py ...` invocation."""

    def __init__(self, completed):
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr

    @property
    def rows(self):
        """Parsed stdout, as a list of rows (header first)."""
        return parse_csv(self.stdout)


@pytest.fixture
def run_cli():
    def _run(*args):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *[str(a) for a in args]],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        return CliResult(completed)

    return _run


@pytest.fixture
def text_file(tmp_path):
    """Write `text` as UTF-8 to `name`, gzipping it when `name` ends with `.gz`."""

    def _write(name, text):
        path = tmp_path / name
        data = text.encode("utf-8")
        path.write_bytes(gzip.compress(data) if name.endswith(".gz") else data)
        return path

    return _write


@pytest.fixture
def csv_file(text_file):
    """Alias of `text_file`, for tests whose subject is a CSV input."""
    return text_file


@pytest.fixture
def jsonl_file(text_file):
    """Write `records` (dicts) as one JSON object per line."""

    def _write(name, records):
        return text_file(name, "".join(json.dumps(record) + "\n" for record in records))

    return _write


@pytest.fixture
def parquet_file(tmp_path):
    """Write `columns` (a name → list mapping, or an arrow Table) as Parquet."""

    def _write(name, columns, schema=None):
        table = columns if isinstance(columns, pa.Table) else pa.table(columns, schema=schema)
        path = tmp_path / name
        if name.endswith(".gz"):
            buffer = io.BytesIO()
            pq.write_table(table, buffer)
            path.write_bytes(gzip.compress(buffer.getvalue()))
        else:
            pq.write_table(table, path)
        return path

    return _write


def parse_csv(text):
    return list(csv.reader(io.StringIO(text, newline="")))


@pytest.fixture
def tree():
    """List every file under a directory, as sorted `/`-joined relative paths."""

    def _tree(root):
        root = Path(root)
        return sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        )

    return _tree
