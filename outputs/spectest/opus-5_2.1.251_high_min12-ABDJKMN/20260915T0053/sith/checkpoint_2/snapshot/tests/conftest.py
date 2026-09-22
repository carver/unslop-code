"""Shared helpers for the sith spec tests."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITH = os.path.join(ROOT, "sith.py")
PY = sys.executable

CURSOR = "█"  # block character marks the cursor in test fixtures


def split_cursor(code):
    """Return (source_without_marker, line, col) for source containing CURSOR."""
    assert code.count(CURSOR) == 1, "fixture must contain exactly one cursor marker"
    idx = code.index(CURSOR)
    before = code[:idx]
    line = before.count("\n") + 1
    col = len(before) - (before.rfind("\n") + 1)
    return code.replace(CURSOR, ""), line, col


def run_raw(*args, cwd=None):
    """Run sith.py with raw argv; return CompletedProcess."""
    return subprocess.run(
        [PY, SITH, *[str(a) for a in args]],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )


def run_complete(path, line, col, fuzzy=False, cwd=None):
    args = ["complete", str(path), line, col]
    if fuzzy:
        args.append("--fuzzy")
    return run_raw(*args, cwd=cwd)


def write_source(tmp_path, code, name="sample.py"):
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


def complete_at(tmp_path, code, fuzzy=False, name="sample.py", extra=None):
    """Write `code` (with a CURSOR marker) and complete there.

    Returns the decoded JSON object.  Asserts exit 0 and clean stdout framing.
    `extra` is a dict of sibling files to create alongside.
    """
    for fname, content in (extra or {}).items():
        (tmp_path / fname).write_text(content, encoding="utf-8")
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    proc = run_complete(path, line, col, fuzzy=fuzzy, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def names(data):
    return [c["name"] for c in data["completions"]]


def entry(data, name):
    for c in data["completions"]:
        if c["name"] == name:
            return c
    raise AssertionError("%r not among %r" % (name, names(data)[:60]))


def has(data, name):
    return any(c["name"] == name for c in data["completions"])


@pytest.fixture
def cursor():
    return CURSOR


# --- infer / goto helpers -------------------------------------------------

def run_infer(path, line, col, cwd=None):
    return run_raw("infer", str(path), line, col, cwd=cwd)


def run_goto(path, line, col, cwd=None):
    return run_raw("goto", str(path), line, col, cwd=cwd)


def _at(tmp_path, code, cmd, name="example.py", extra=None):
    """Write `code` (with one CURSOR marker) plus `extra` siblings, run `cmd`."""
    for fname, content in (extra or {}).items():
        target = tmp_path / fname
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    return run_raw(cmd, str(path), line, col, cwd=str(tmp_path))


def infer_raw(tmp_path, code, name="example.py", extra=None):
    return _at(tmp_path, code, "infer", name=name, extra=extra)


def goto_raw(tmp_path, code, name="example.py", extra=None):
    return _at(tmp_path, code, "goto", name=name, extra=extra)


def infer_at(tmp_path, code, name="example.py", extra=None):
    """Run `infer`; assert exit 0 and return the `definitions` list."""
    proc = infer_raw(tmp_path, code, name=name, extra=extra)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"definitions"}
    return data["definitions"]


def goto_at(tmp_path, code, name="example.py", extra=None):
    """Run `goto`; assert exit 0 and return the `definitions` list."""
    proc = goto_raw(tmp_path, code, name=name, extra=extra)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"definitions"}
    return data["definitions"]


def one(definitions):
    assert len(definitions) == 1, definitions
    return definitions[0]


def dnames(definitions):
    return [d["name"] for d in definitions]
