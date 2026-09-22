"""Shared helpers for the xjq.py CLI tests.

Every test drives the real executable exactly as the spec documents it:

    python xjq.py [OPTIONS] QUERY [INFILE]

with the document arriving on stdin.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
XJQ = REPO_ROOT / "xjq.py"


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def lines(self):
        """stdout split into lines, ignoring the trailing newline (see T10)."""
        out = self.stdout
        if out.endswith("\n"):
            out = out[:-1]
        return out.split("\n") if out else []


def run(query, stdin="", *extra_args, cwd=None):
    """Run `python xjq.py QUERY [extra...]` feeding `stdin` to the process."""
    cmd = [sys.executable, str(XJQ), query, *extra_args]
    proc = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        timeout=60,
    )
    return Result(proc.returncode, proc.stdout, proc.stderr)


@pytest.fixture
def xjq():
    return run
