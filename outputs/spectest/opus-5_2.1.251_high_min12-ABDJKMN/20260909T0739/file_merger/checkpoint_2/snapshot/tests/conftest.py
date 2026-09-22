"""Shared helpers for the merge_files.py spec suite."""
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "merge_files.py"


class Result:
    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def ok(self):
        return self.returncode == 0

    def rows(self):
        """Parse stdout as the tool's output CSV dialect."""
        return parse_csv(self.stdout)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Result(rc={self.returncode}, out={self.stdout!r}, err={self.stderr!r})"


def parse_csv(text):
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"'))


def run(*args, cwd=None):
    """Invoke the tool with the given argv tail."""
    proc = subprocess.run(
        [sys.executable, str(TOOL), *[str(a) for a in args]],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return Result(proc)


def write(tmp_path, name, text):
    """Write a fixture file verbatim (LF line endings) and return its path."""
    p = Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return p


def write_schema(tmp_path, name, columns):
    """columns: list of (name, type) pairs."""
    doc = {"columns": [{"name": n, "type": t} for n, t in columns]}
    return write(tmp_path, name, json.dumps(doc))


def merge(tmp_path, files, *args):
    """Write `files` ({name: text}) into tmp_path and merge them to stdout.

    Extra args are inserted before the inputs; inputs are passed in dict order.
    """
    paths = [write(tmp_path, n, t) for n, t in files.items()]
    return run("--output", "-", *args, *paths, cwd=tmp_path)


@pytest.fixture
def tool():
    assert TOOL.exists(), f"{TOOL} must exist"
    return TOOL


# --------------------------------------------------------------------------
# Checkpoint 2 helpers: heterogeneous inputs (TSV, JSONL, Parquet, gzip)
# --------------------------------------------------------------------------
import gzip  # noqa: E402


def write_bytes(tmp_path, name, data):
    """Write raw bytes and return the path."""
    p = Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def write_gz(tmp_path, name, text):
    """Write `text` gzip-compressed under `name`."""
    return write_bytes(tmp_path, name, gzip.compress(text.encode("utf-8")))


def jsonl_text(records):
    return "".join(json.dumps(r) + "\n" for r in records)


def write_jsonl(tmp_path, name, records):
    return write(tmp_path, name, jsonl_text(records))


def write_jsonl_gz(tmp_path, name, records):
    return write_gz(tmp_path, name, jsonl_text(records))


def write_tsv(tmp_path, name, rows):
    """rows: list of lists of str; first row is the header."""
    return write(tmp_path, name, "".join("\t".join(r) + "\n" for r in rows))


def pa_modules():
    """Import pyarrow lazily so non-parquet tests never need it."""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    return pa, pq


def write_parquet(tmp_path, name, records, schema=None, row_group_size=None):
    """Write a list of dicts as a parquet file and return its path."""
    pa, pq = pa_modules()
    p = Path(tmp_path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records, schema=schema)
    kwargs = {}
    if row_group_size is not None:
        kwargs["row_group_size"] = row_group_size
    pq.write_table(table, str(p), **kwargs)
    return p


def merge_paths(paths, *args, cwd=None):
    """Merge already-written input paths to stdout."""
    return run("--output", "-", *args, *[str(p) for p in paths],
               cwd=cwd or (Path(paths[0]).parent if paths else None))
