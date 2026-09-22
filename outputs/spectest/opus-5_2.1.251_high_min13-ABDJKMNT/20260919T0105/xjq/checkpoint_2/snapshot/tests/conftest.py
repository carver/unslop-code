"""Shared helpers for driving the `xjq.py` CLI as a subprocess."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"


@dataclass
class Result:
    """Outcome of one CLI invocation."""

    stdout: str
    stderr: str
    returncode: int

    @property
    def lines(self):
        """Stdout split into lines, with the trailing newline (if any) ignored."""
        return self.stdout.splitlines()


@pytest.fixture
def run_xjq():
    """Run `python xjq.py <args>` feeding `stdin` in, and capture the result."""

    def _run(*args, stdin=""):
        data = stdin.encode() if isinstance(stdin, str) else stdin
        completed = subprocess.run(
            [sys.executable, str(XJQ), *args],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return Result(
            stdout=completed.stdout.decode(),
            stderr=completed.stderr.decode(),
            returncode=completed.returncode,
        )

    return _run
