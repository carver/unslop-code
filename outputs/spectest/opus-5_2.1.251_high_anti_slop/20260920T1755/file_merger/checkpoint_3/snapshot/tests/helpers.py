"""Shared plumbing for driving the CLI the way a user would."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "merge_files.py"), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def merged_rows(*args: str) -> list[list[str]]:
    """Run a merge to stdout and return its rows, header included."""
    result = run_cli("--output", "-", *args)
    assert result.returncode == 0, result.stderr
    return list(csv.reader(result.stdout.splitlines()))
