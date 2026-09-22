"""Shared helpers for driving the `sith.py` CLI from tests."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITH = ROOT / "sith.py"


class Result:
    """Outcome of one `sith.py complete` invocation."""

    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def payload(self):
        return json.loads(self.stdout)

    @property
    def completions(self):
        return self.payload["completions"]

    @property
    def names(self):
        return [c["name"] for c in self.completions]

    def by_name(self, name):
        for completion in self.completions:
            if completion["name"] == name:
                return completion
        raise AssertionError(f"{name!r} not in {self.names[:40]}")


def run_cli(*args, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(SITH), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    return Result(proc)


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def complete(workdir):
    """Write `source` to a file and complete at a cursor marker or explicit position.

    The marker ``|`` in the source denotes the cursor; it is stripped before
    the file is written.  Alternatively pass explicit ``line``/``col``.
    """

    def _complete(source, line=None, col=None, fuzzy=False, name="sample.py", expect_ok=True):
        if line is None:
            line, col, source = _split_marker(source)
        path = workdir / name
        path.write_text(source, encoding="utf-8")
        args = ["complete", str(path), line, col]
        if fuzzy:
            args.append("--fuzzy")
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _complete


def _split_marker(source):
    lines = source.split("\n")
    for index, text in enumerate(lines):
        if "|" in text:
            col = text.index("|")
            lines[index] = text.replace("|", "", 1)
            return index + 1, col, "\n".join(lines)
    raise AssertionError("source has no '|' cursor marker")
