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


# --- infer / goto helpers -------------------------------------------------

def run_defs(cmd, path, line, col, extra=()):
    return run_raw([cmd, str(path), str(line), str(col)] + list(extra))


def defs(tmp_path, src, cmd, name="main.py", extra=()):
    """Run `infer`/`goto` on `src` (with a <|> cursor marker); assert success."""
    body, line, col = split_cursor(src)
    p = write(tmp_path, body, name)
    r = run_defs(cmd, p, line, col, extra)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["definitions"]


def infer(tmp_path, src, name="main.py", extra=()):
    return defs(tmp_path, src, "infer", name, extra)


def goto(tmp_path, src, name="main.py", extra=()):
    return defs(tmp_path, src, "goto", name, extra)


def raw(tmp_path, src, cmd, name="main.py", extra=()):
    """Same, but hand back the raw process so the test can inspect exit codes."""
    body, line, col = split_cursor(src)
    p = write(tmp_path, body, name)
    return run_defs(cmd, p, line, col, extra)


def one(definitions):
    assert len(definitions) == 1, "expected exactly one definition: %r" % (definitions,)
    return definitions[0]


def typenames(definitions):
    return sorted(d["name"] for d in definitions)


@pytest.fixture
def dhelpers():
    import types
    return types.SimpleNamespace(
        split_cursor=split_cursor, write=write, run_raw=run_raw, defs=defs,
        infer=infer, goto=goto, raw=raw, one=one, typenames=typenames,
        run_defs=run_defs, sith=SITH,
    )
