"""Shared helpers for driving the `sith.py` CLI from tests."""
import functools
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITH = ROOT / "sith.py"


class Result:
    """Outcome of one `sith.py` invocation."""

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
    def definitions(self):
        return self.payload["definitions"]

    @property
    def only(self):
        """The single definition returned, asserting there is exactly one."""
        assert len(self.definitions) == 1, self.definitions
        return self.definitions[0]

    @property
    def definition_names(self):
        return [d["name"] for d in self.definitions]

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
    `files` writes extra project files, and `project` passes ``--project``.
    """

    def _complete(source, line=None, col=None, fuzzy=False, name="sample.py", expect_ok=True,
                  files=None, project=None):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = ["complete", str(workdir / name), line, col]
        if fuzzy:
            args.append("--fuzzy")
        if project is not None:
            args += ["--project", str(workdir / project)]
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


def _write_files(workdir, files):
    for name, text in files.items():
        path = workdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def navigate(workdir):
    """Run `infer`/`goto` at the `|` marker, with optional extra project files."""

    def _navigate(command, source, line=None, col=None, name="sample.py", files=None,
                  expect_ok=True, project=None, follow_imports=False):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = [command, str(workdir / name), line, col]
        if project is not None:
            args += ["--project", str(workdir / project)]
        if follow_imports:
            args.append("--follow-imports")
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _navigate


@pytest.fixture
def infer(navigate):
    return functools.partial(navigate, "infer")


@pytest.fixture
def goto(navigate):
    return functools.partial(navigate, "goto")
