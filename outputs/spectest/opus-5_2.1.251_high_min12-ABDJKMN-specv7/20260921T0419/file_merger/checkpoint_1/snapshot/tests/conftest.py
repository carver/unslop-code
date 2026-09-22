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
