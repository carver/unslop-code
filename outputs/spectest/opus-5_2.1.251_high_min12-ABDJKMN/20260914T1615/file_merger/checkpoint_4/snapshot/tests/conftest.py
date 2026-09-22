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


# ---------------------------------------------------------------------------
# Helpers for the multi-format checkpoint (TSV / JSONL / Parquet / gzip)
# ---------------------------------------------------------------------------

import gzip as _gzip


def write_bytes(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)
    return str(p)


def write_gz(path, text):
    """Write `text` gzip-compressed to `path` (UTF-8, LF preserved)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _gzip.open(p, "wb") as fh:
        fh.write(text.encode("utf-8"))
    return str(p)


def write_tsv(path, header_row, rows):
    """header_row: list of names; rows: list of lists of raw field text."""
    out = ["\t".join(header_row)]
    out += ["\t".join(r) for r in rows]
    return write(path, "\n".join(out) + "\n")


def jsonl_text(objs):
    return "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs)


def write_jsonl(path, objs):
    return write(path, jsonl_text(objs))


def write_jsonl_gz(path, objs):
    return write_gz(path, jsonl_text(objs))


def pa():
    """Import pyarrow, skipping the test if it is unavailable."""
    return pytest.importorskip("pyarrow")


def write_parquet(path, columns, schema=None, row_group_size=None):
    """columns: dict name -> list of python values (pyarrow infers types).

    `schema` may be a pyarrow.Schema for exact control of the column types.
    """
    pyarrow = pa()
    import pyarrow.parquet as pq

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if schema is not None:
        table = pyarrow.table(columns, schema=schema)
    else:
        table = pyarrow.table(columns)
    kw = {}
    if row_group_size is not None:
        kw["row_group_size"] = row_group_size
    pq.write_table(table, str(p), **kw)
    return str(p)


def gzip_existing(src, dest):
    """gzip-compress an existing file byte-for-byte."""
    with open(src, "rb") as fh:
        data = fh.read()
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _gzip.open(p, "wb") as out:
        out.write(data)
    return str(p)


# ---------------------------------------------------------------------------
# Helpers for the nested-types checkpoint
# ---------------------------------------------------------------------------

def write_json(path, obj):
    """Write any JSON document (schema, alias file, ...) to `path`."""
    return write(path, json.dumps(obj))


def write_nested_schema(path, columns):
    """columns: list of (name, type) where type may be a nested JSON type."""
    return write_json(path, {"columns": [{"name": n, "type": t}
                                         for n, t in columns]})


def write_aliases(path, mapping):
    return write_json(path, {"aliases": mapping})


def struct_t(*fields):
    """struct_t(("a", "int"), ("b", "string")) -> the struct type JSON."""
    return {"struct": {"fields": [{"name": n, "type": t} for n, t in fields]}}


def array_t(element):
    return {"array": {"element": element}}


def map_t(value, key="string"):
    return {"map": {"key": key, "value": value}}


def cells(text, name):
    """The raw (CSV-decoded) values of one output column, in output order."""
    return col(text, name)


def json_cells(text, name):
    """Parse each cell of a nested column back into a Python object."""
    return [json.loads(c) for c in col(text, name)]


def raw_json_cells(text, name):
    """The exact JSON text of each cell of a nested column (post CSV decode)."""
    return col(text, name)
