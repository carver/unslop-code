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


def run(*args: str, stdin: str | bytes = "") -> Result:
    """Run `python xjq.py *args` feeding `stdin`, capturing both streams.

    Text on `stdin` is sent as UTF-8; bytes are sent as they are, which is how
    a test feeds input in another encoding.
    """
    completed = subprocess.run(
        [sys.executable, str(XJQ), *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
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


CSS_DOC = """<div id="wrap">
  <p class="lead">Hello <b>bold</b> world</p>
  <p class="lead">Second</p>
  <span>Span text</span>
</div>
"""

# Mixed content in one element and nesting two levels deep, so that direct and
# descendant text extraction produce visibly different line lists.
NESTED_DOC = """<article>
  <h1>Title</h1>
  <section>
    <p>outer <em>inner</em> tail</p>
  </section>
</article>
"""


# A top-level object exercising every JSON kind: strings, both number kinds,
# booleans, null, a nested object and a nested array.
JSON_OBJECT = """{
  "title": "Dune",
  "year": 1965,
  "rating": 4.5,
  "inPrint": true,
  "sequel": null,
  "author": {"first": "Frank", "last": "Herbert"},
  "tags": ["scifi", "classic"]
}"""

JSON_ARRAY = '[{"id": 1}, {"id": 2}, "loose"]'
