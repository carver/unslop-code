"""Shared helpers for the merge_files.py CLI tests."""

import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "merge_files.py"


def _write(path: Path, text: str) -> Path:
    """Write `text` verbatim (no newline translation) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


@pytest.fixture
def workdir(tmp_path):
    """Directory the tool is run from; inputs and outputs live here."""
    return tmp_path


@pytest.fixture
def csv_file(workdir):
    """Create a CSV input file: csv_file("a.csv", "id\\n1\\n")."""

    def make(name: str, text: str) -> Path:
        return _write(workdir / name, text)

    return make


@pytest.fixture
def run_tool(workdir):
    """Run merge_files.py with the given arguments and capture the result."""

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOL), *[str(arg) for arg in args]],
            cwd=workdir,
            capture_output=True,
            text=True,
        )

    return run


def parse_csv(text: str) -> list[list[str]]:
    """Parse tool output back into rows using the fixed output dialect."""
    return list(csv.reader(io.StringIO(text, newline="")))


def rows_of(text: str) -> list[list[str]]:
    """Data rows of tool output, header dropped."""
    return parse_csv(text)[1:]


def header_of(text: str) -> list[str]:
    """Header row of tool output."""
    return parse_csv(text)[0]


def column(text: str, name: str) -> list[str]:
    """Values of one output column, in output order."""
    index = header_of(text).index(name)
    return [row[index] for row in rows_of(text)]
