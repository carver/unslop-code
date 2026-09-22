"""Shared helpers: every test drives the real CLI the way the spec documents it."""

import csv
import io
import subprocess
import sys
from pathlib import Path

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
def csv_file(tmp_path):
    """Write `text` as a UTF-8 CSV named `name` under tmp_path, return its path."""

    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write


def parse_csv(text):
    return list(csv.reader(io.StringIO(text, newline="")))
