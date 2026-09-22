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

    def rows(self):
        """Parse stdout as CSV (default dialect)."""
        import csv
        import io

        return list(csv.reader(io.StringIO(self.stdout)))


def run_tool(*args, cwd=None, timeout=120):
    cmd = [sys.executable, str(SCRIPT)] + [str(a) for a in args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return Result(proc)


@pytest.fixture
def run():
    return run_tool


@pytest.fixture
def work(tmp_path):
    """Helper object for building input files inside a tmp dir."""

    class Work:
        def __init__(self, base):
            self.base = base

        def write(self, name, text):
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return p

        def csv(self, name, header, rows):
            lines = [",".join(header)]
            lines += [",".join(str(c) for c in r) for r in rows]
            return self.write(name, "\n".join(lines) + "\n")

        def schema(self, name, columns):
            import json

            return self.write(
                name,
                json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]}),
            )

        def tsv(self, name, header, rows, newline="\n"):
            lines = ["\t".join(header)]
            lines += ["\t".join(str(c) for c in r) for r in rows]
            return self.write(name, newline.join(lines) + newline)

        def jsonl(self, name, objects):
            import json

            text = "".join(json.dumps(o) + "\n" for o in objects)
            return self.write(name, text)

        def raw(self, name, data):
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            return p

        def gzip(self, name, text):
            """Write gzip-compressed text (text may be str or bytes)."""
            import gzip as _gzip

            if isinstance(text, str):
                text = text.encode("utf-8")
            return self.raw(name, _gzip.compress(text))

        def gzip_file(self, name, source):
            """Gzip an existing file's bytes to `name`."""
            import gzip as _gzip

            return self.raw(name, _gzip.compress(Path(source).read_bytes()))

        def parquet(self, name, rows, schema=None):
            """Write a Parquet file from a list of dicts."""
            pa = pytest.importorskip("pyarrow")
            pq = pytest.importorskip("pyarrow.parquet")
            table = pa.Table.from_pylist(rows, schema=schema)
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, str(p))
            return p

        def path(self, name):
            return self.base / name

    return Work(tmp_path)


def parse_csv_text(text):
    import csv
    import io

    return list(csv.reader(io.StringIO(text)))


def body(result):
    """Rows of stdout CSV without the header."""
    return result.rows()[1:]


def header(result):
    return result.rows()[0]


def tree(root):
    """Relative posix paths of every file under `root`, sorted."""
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def dirs(root):
    """Relative posix paths of every directory under `root`, sorted."""
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())


def read_csv_file(path):
    import csv

    with open(str(path), newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def siblings(root):
    """Names next to `root` in its parent -- used to spot leftover temp dirs."""
    root = Path(root)
    return sorted(p.name for p in root.parent.iterdir() if p.name != root.name)
