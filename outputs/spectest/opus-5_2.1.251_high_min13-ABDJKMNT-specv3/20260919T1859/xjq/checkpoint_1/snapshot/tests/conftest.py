"""Shared helpers for driving the ``xjq.py`` CLI as a subprocess."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"


@dataclass
class Result:
    """Outcome of one ``xjq.py`` invocation."""

    stdout: str
    stderr: str
    returncode: int


@pytest.fixture
def run_xjq():
    """Run ``xjq.py`` with the given argv, feeding ``stdin`` on standard input."""

    def run(*args: str, stdin: str = "") -> Result:
        completed = subprocess.run(
            [sys.executable, str(XJQ), *args],
            input=stdin.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return Result(
            stdout=completed.stdout.decode(),
            stderr=completed.stderr.decode(),
            returncode=completed.returncode,
        )

    return run


BOOKS = """<?xml version="1.0"?>
<library>
  <book id="b1" lang="en">
    <title>Dune</title>
    <author>Frank Herbert</author>
  </book>
  <book id="b2" lang="fr">
    <title>Les Miserables</title>
    <author>Victor Hugo</author>
  </book>
</library>
"""
