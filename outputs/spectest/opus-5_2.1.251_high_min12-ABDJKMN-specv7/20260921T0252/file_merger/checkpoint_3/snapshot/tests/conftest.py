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


# ==========================================================================
# Checkpoint 2 helpers: heterogeneous inputs (TSV / JSONL / Parquet / gzip)
# ==========================================================================
import gzip as _gzip

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAVE_PARQUET = True
except ImportError:  # pragma: no cover - environment without pyarrow
    pa = None
    pq = None
    HAVE_PARQUET = False

needs_parquet = pytest.mark.skipif(not HAVE_PARQUET,
                                   reason="pyarrow is required")


def write_bytes(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(data)
    return str(path)


def write_gz(path, text):
    """Write *text* gzip compressed to *path*."""
    return write_bytes(path, _gzip.compress(text.encode("utf-8")))


def write_tsv(path, lines):
    """Write raw TSV lines (already tab joined) with \\n endings."""
    return write_file(path, "\n".join(lines) + "\n")


def write_jsonl(path, objects):
    """Write one JSON document per line.

    Strings in *objects* are emitted verbatim so malformed lines can be
    produced on purpose.
    """
    out = []
    for obj in objects:
        out.append(obj if isinstance(obj, str) else json.dumps(obj))
    return write_file(path, "\n".join(out) + "\n")


def write_jsonl_gz(path, objects):
    out = []
    for obj in objects:
        out.append(obj if isinstance(obj, str) else json.dumps(obj))
    return write_gz(path, "\n".join(out) + "\n")


def write_parquet(path, columns, schema=None, row_group_size=None):
    """Write a Parquet file.

    *columns* is an ordered dict of column name -> list of values.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema is not None:
        table = pa.table(dict(columns), schema=schema)
    else:
        table = pa.table(dict(columns))
    kwargs = {}
    if row_group_size:
        kwargs["row_group_size"] = row_group_size
    pq.write_table(table, str(path), **kwargs)
    return str(path)


def parse_csv_dialect(text, quotechar='"'):
    """Reader for output written with a non-default quote character."""
    rows = []
    field = []
    row = []
    in_quotes = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == quotechar:
                if i + 1 < n and text[i + 1] == quotechar:
                    field.append(quotechar)
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            field.append(ch)
            i += 1
            continue
        if ch == quotechar and not field:
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


def header(rows):
    return rows[0]


# ==========================================================================
# Checkpoint 3 helpers: partitioned / sharded directory output
# ==========================================================================
def tree_files(root):
    """Every regular file under *root* as sorted root-relative posix paths."""
    root = pathlib.Path(root)
    if not root.exists():
        return []
    out = []
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        for name in filenames:
            full = pathlib.Path(dirpath) / name
            out.append(full.relative_to(root).as_posix())
    return sorted(out)


def tree_dirs(root):
    """Every directory under *root* as sorted root-relative posix paths."""
    root = pathlib.Path(root)
    if not root.exists():
        return []
    out = []
    for dirpath, dirnames, _filenames in os.walk(str(root)):
        for name in dirnames:
            full = pathlib.Path(dirpath) / name
            out.append(full.relative_to(root).as_posix())
    return sorted(out)


def read_text(path):
    with open(str(path), "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def read_rows(path):
    """Parse one output CSV file into rows (header included)."""
    return parse_csv(read_text(path))


def part_files(directory):
    """Sorted part-xxxxx.csv names directly inside *directory*."""
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if p.is_file() and p.name.startswith("part-"))


def concat_body(directory):
    """Data rows of every part file in *directory*, in part-file order."""
    directory = pathlib.Path(directory)
    rows = []
    for name in part_files(directory):
        rows.extend(read_rows(directory / name)[1:])
    return rows


def concat_col(directory, name):
    """One named column across every part file of *directory*, in order."""
    directory = pathlib.Path(directory)
    values = []
    for fname in part_files(directory):
        rows = read_rows(directory / fname)
        idx = rows[0].index(name)
        values.extend(r[idx] for r in rows[1:])
    return values
