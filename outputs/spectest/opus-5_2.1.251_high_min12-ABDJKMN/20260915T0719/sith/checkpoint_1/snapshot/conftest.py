import json
import subprocess
import sys
from itertools import groupby
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SITH = str(ROOT / "sith.py")
MARK = "<|>"


def split_cursor(src):
    """Turn a source string containing the <|> marker into (source, line, col)."""
    idx = src.index(MARK)
    before = src[:idx]
    line = before.count("\n") + 1
    col = len(before) - (before.rfind("\n") + 1)
    return src.replace(MARK, "", 1), line, col


def write(tmp_path, src, name="main.py"):
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return p


def run_raw(args):
    return subprocess.run([sys.executable, SITH] + list(args),
                          capture_output=True, text=True)


def run(path, line, col, fuzzy=False):
    args = ["complete", str(path), str(line), str(col)]
    if fuzzy:
        args.append("--fuzzy")
    return run_raw(args)


def complete(tmp_path, src, fuzzy=False, name="main.py"):
    """Run the tool on `src` (which embeds a <|> cursor marker); assert success."""
    body, line, col = split_cursor(src)
    p = write(tmp_path, body, name)
    r = run(p, line, col, fuzzy)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["completions"]


def names(comps):
    return [c["name"] for c in comps]


def find(comps, name):
    for c in comps:
        if c["name"] == name:
            return c
    return None


def group_rank(comp):
    """0 public, 1 private, 2 dunder, 3 keyword -- per the spec's ordering rules."""
    if comp["type"] == "keyword":
        return 3
    n = comp["name"]
    if n.startswith("__") and n.endswith("__"):
        return 2
    if n.startswith("_"):
        return 1
    return 0


def assert_ordering(comps):
    ranks = [group_rank(c) for c in comps]
    assert ranks == sorted(ranks), "groups out of order: %r" % (ranks,)
    for _rank, grp in groupby(zip(ranks, comps), key=lambda t: t[0]):
        lowered = [c["name"].lower() for _r, c in grp]
        assert lowered == sorted(lowered), "not alphabetical: %r" % (lowered,)


@pytest.fixture
def helpers():
    import types
    ns = types.SimpleNamespace(
        split_cursor=split_cursor, write=write, run_raw=run_raw, run=run,
        complete=complete, names=names, find=find, group_rank=group_rank,
        assert_ordering=assert_ordering, sith=SITH,
    )
    return ns
