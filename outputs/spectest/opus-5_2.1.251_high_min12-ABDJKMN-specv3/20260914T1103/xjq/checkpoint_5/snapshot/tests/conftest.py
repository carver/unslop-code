"""Shared fixtures: every test drives the real CLI through a subprocess."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
XJQ = REPO_ROOT / "xjq.py"


class Result:
    def __init__(self, completed):
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr

    def __repr__(self):
        return (
            f"Result(returncode={self.returncode!r}, "
            f"stdout={self.stdout!r}, stderr={self.stderr!r})"
        )


def _run(args, stdin_text):
    data = stdin_text.encode("utf-8") if isinstance(stdin_text, str) else stdin_text
    completed = subprocess.run(
        [sys.executable, str(XJQ), *args],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    return Result(
        subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8"),
        )
    )


@pytest.fixture
def xjq():
    """Run `python xjq.py <args>` with `stdin` piped in."""

    def run(*args, stdin=""):
        return _run(list(args), stdin)

    return run


BOOKS = """<?xml version="1.0" encoding="UTF-8"?>
<library name="City Central">
  <book id="b1" lang="en">
    <title>Dune</title>
    <author>Frank Herbert</author>
    <year>1965</year>
  </book>
  <book id="b2" lang="fr">
    <title>Le Petit Prince</title>
    <author>Antoine de Saint-Exupery</author>
    <year>1943</year>
  </book>
  <book id="b3" lang="en">
    <title>Neuromancer</title>
    <author>William Gibson</author>
    <year>1984</year>
  </book>
</library>
"""


@pytest.fixture
def books():
    return BOOKS


PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<page>
  <div class="post" id="p1">
    <h2>First</h2>
    <p>Hello <b>bold</b> world</p>
  </div>
  <div class="post" id="p2">
    <h2>Second</h2>
    <p>Bye</p>
  </div>
</page>
"""


@pytest.fixture
def page():
    return PAGE


MIXED = "<doc><p>Hello <b>bold</b> world</p></doc>"


@pytest.fixture
def mixed():
    """A single <p> with mixed content: text, child element, tail text."""
    return MIXED
