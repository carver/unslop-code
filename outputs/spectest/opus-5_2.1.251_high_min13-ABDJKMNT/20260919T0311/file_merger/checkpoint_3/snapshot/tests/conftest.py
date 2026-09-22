"""Shared helpers: every test drives the CLI as a black box, exactly as the
spec's usage section describes it."""
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOL = PROJECT_ROOT / "merge_files.py"


@pytest.fixture
def run(tmp_path):
    """Invoke `python merge_files.py ...` from inside the test's tmp dir."""

    def _run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, str(TOOL), *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
        )

    return _run


@pytest.fixture
def csv_file(tmp_path):
    """Write a CSV given its exact text; returns the path."""

    def _csv_file(name, text):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return _csv_file


@pytest.fixture
def schema_file(tmp_path):
    """Write a schema JSON from a list of (name, type) pairs."""

    def _schema_file(columns, name="schema.json"):
        import json

        path = tmp_path / name
        path.write_text(
            json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]}),
            encoding="utf-8",
        )
        return path

    return _schema_file


def lines(stdout):
    """Output rows as raw text lines, without the trailing empty element."""
    assert stdout.endswith("\n") or stdout == ""
    return stdout.split("\n")[:-1]


def table(stdout):
    """Output parsed back through csv, as a list of rows."""
    import csv
    import io

    return list(csv.reader(io.StringIO(stdout)))


def column(stdout, name):
    """Values of one output column, in output order."""
    rows = table(stdout)
    idx = rows[0].index(name)
    return [r[idx] for r in rows[1:]]


@pytest.fixture
def text_file(tmp_path):
    """Write any text input (TSV, JSONL, ...) verbatim; returns the path."""

    def _text_file(name, text):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return _text_file


@pytest.fixture
def gz_file(tmp_path):
    """Write text gzip-compressed under `name`; returns the path."""

    def _gz_file(name, text):
        import gzip

        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wb") as fh:
            fh.write(text.encode("utf-8"))
        return path

    return _gz_file


@pytest.fixture
def jsonl_file(text_file):
    """Write a JSON Lines file from a list of objects."""

    def _jsonl_file(name, objects):
        import json

        return text_file(name, "".join(json.dumps(o) + "\n" for o in objects))

    return _jsonl_file


@pytest.fixture
def parquet_file(tmp_path):
    """Write a Parquet file from a pyarrow table spec: {column: (values, type)}."""

    def _parquet_file(name, columns, **writer_kwargs):
        import pyarrow as pa
        import pyarrow.parquet as pq

        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {name: pa.array(values, type=type_) for name, (values, type_) in columns.items()}
        )
        pq.write_table(table, path, **writer_kwargs)
        return path

    return _parquet_file


def tree(root):
    """Every file under `root` as sorted POSIX-relative paths."""
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def parts(directory):
    """The `part-xxxxx.csv` files of one directory, in numeric order."""
    return sorted(Path(directory).glob("part-*.csv"), key=lambda p: p.name)


def data_rows(path):
    """The data rows of one part file, parsed back through csv."""
    import csv

    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))[1:]
