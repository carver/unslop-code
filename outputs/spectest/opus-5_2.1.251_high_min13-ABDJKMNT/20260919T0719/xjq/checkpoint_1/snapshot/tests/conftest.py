"""Shared helpers for driving the xjq.py CLI as a subprocess."""

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


def run(*args: str, stdin: str = "") -> Result:
    """Run `python xjq.py *args` feeding `stdin`, capturing both streams."""
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


@pytest.fixture
def xjq():
    return run


DOC = """<?xml version="1.0"?>
<library>
  <book id="b1" lang="en">
    <title>Dune</title>
    <author>Frank Herbert</author>
  </book>
  <book id="b2" lang="fr">
    <title>Le Petit Prince</title>
    <author>Antoine de Saint-Exupery</author>
  </book>
</library>
"""

MIXED_CASE_DOC = "<Root><Item>upper</Item><item>lower</item></Root>"

HTMLISH_DOC = """<html>
  <body>
    <div class="post">
      <p>Hello   world</p>
      <a href="/one">One</a>
      <a href="/two">Two</a>
    </div>
  </body>
</html>
"""
