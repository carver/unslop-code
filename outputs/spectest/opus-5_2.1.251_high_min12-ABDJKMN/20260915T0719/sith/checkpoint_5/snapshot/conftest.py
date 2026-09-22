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


# --- multi-file project helpers (import resolution spec) ------------------

def make_project(tmp_path, files):
    """Write a {relative path: source} mapping under tmp_path; return tmp_path."""
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _place(tmp_path, files):
    """Write `files`, one of which holds the <|> marker; return (path, line, col)."""
    target = None
    written = {}
    for rel, text in files.items():
        if MARK in text:
            assert target is None, "more than one cursor marker"
            body, line, col = split_cursor(text)
            written[rel] = body
            target = (rel, line, col)
        else:
            written[rel] = text
    assert target is not None, "no <|> cursor marker in project files"
    make_project(tmp_path, written)
    rel, line, col = target
    return tmp_path / rel, line, col


def project_args(tmp_path, project):
    """Extra CLI args for --project: True means "the tmp_path root"."""
    if project is None:
        return []
    if project is True:
        return ["--project", str(tmp_path)]
    return ["--project", str(tmp_path / project) if not str(project).startswith("/")
            else str(project)]


def prun(cmd, tmp_path, files, extra=(), project=None):
    """Run `cmd` on a multi-file project; hand back the raw process."""
    path, line, col = _place(tmp_path, files)
    args = [cmd, str(path), str(line), str(col)]
    args += list(extra) + project_args(tmp_path, project)
    return run_raw(args)


def pdefs(cmd, tmp_path, files, extra=(), project=None):
    r = prun(cmd, tmp_path, files, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["definitions"]


def pinfer(tmp_path, files, extra=(), project=None):
    return pdefs("infer", tmp_path, files, extra, project)


def pgoto(tmp_path, files, extra=(), project=None):
    return pdefs("goto", tmp_path, files, extra, project)


def pcomplete(tmp_path, files, extra=(), project=None):
    r = prun("complete", tmp_path, files, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["completions"]


@pytest.fixture
def phelpers():
    import types
    return types.SimpleNamespace(
        make_project=make_project, prun=prun, pdefs=pdefs, pinfer=pinfer,
        pgoto=pgoto, pcomplete=pcomplete, names=names, find=find, one=one,
        assert_ordering=assert_ordering, sith=SITH,
    )


# --- signatures / references / search / names -----------------------------

def _cursor_cmd(cmd, tmp_path, src, name="main.py", extra=()):
    body, line, col = split_cursor(src)
    p = write(tmp_path, body, name)
    return run_raw([cmd, str(p), str(line), str(col)] + list(extra))


def sigs_raw(tmp_path, src, name="main.py", extra=()):
    return _cursor_cmd("signatures", tmp_path, src, name, extra)


def sigs(tmp_path, src, name="main.py", extra=()):
    r = sigs_raw(tmp_path, src, name, extra)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["signatures"]


def psigs(tmp_path, files, extra=(), project=None):
    r = prun("signatures", tmp_path, files, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["signatures"]


def refs_raw(tmp_path, src, name="main.py", extra=()):
    return _cursor_cmd("references", tmp_path, src, name, extra)


def refs(tmp_path, src, name="main.py", extra=()):
    r = refs_raw(tmp_path, src, name, extra)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["references"]


def prefs(tmp_path, files, extra=(), project=None):
    r = prun("references", tmp_path, files, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["references"]


def search_raw(tmp_path, files, query, extra=(), project=True):
    make_project(tmp_path, files)
    args = ["search", query] + list(extra)
    if project:
        args += ["--project", str(tmp_path)]
    return run_raw(args)


def search(tmp_path, files, query, extra=(), project=True):
    r = search_raw(tmp_path, files, query, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["results"]


def names_raw(tmp_path, files, rel="main.py", extra=(), project=True):
    make_project(tmp_path, files)
    args = ["names", str(tmp_path / rel)] + list(extra)
    if project:
        args += ["--project", str(tmp_path)]
    return run_raw(args)


def file_names(tmp_path, files, rel="main.py", extra=(), project=True):
    r = names_raw(tmp_path, files, rel, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["names"]


def at(items, line, col=None):
    """Entries at a given line (and column)."""
    return [d for d in items
            if d["line"] == line and (col is None or d["column"] == col)]


def positions(references):
    return [(r["module_path"], r["line"], r["column"]) for r in references]


@pytest.fixture
def shelpers():
    import types
    return types.SimpleNamespace(
        sigs=sigs, sigs_raw=sigs_raw, psigs=psigs, refs=refs, refs_raw=refs_raw,
        prefs=prefs, search=search, search_raw=search_raw, names_raw=names_raw,
        file_names=file_names, at=at, positions=positions, find=find,
        make_project=make_project, run_raw=run_raw, sith=SITH,
    )


# --- refactoring / errors (rename, inline, extract-*, errors) -------------

UNTIL = "<^>"


def split_markers(src):
    """Strip `<|>` (cursor) and `<^>` (until) markers; return (body, cursor, until).

    Markers are processed in document order so removing an earlier one does not
    disturb the position computed for a later one.
    """
    body = src
    found = {}
    while True:
        cand = [(body.index(m), m, key) for m, key in ((MARK, "cursor"),
                                                       (UNTIL, "until"))
                if m in body]
        if not cand:
            break
        idx, mark, key = min(cand)
        before = body[:idx]
        found[key] = (before.count("\n") + 1,
                      len(before) - (before.rfind("\n") + 1))
        body = body[:idx] + body[idx + len(mark):]
    return body, found.get("cursor"), found.get("until")


def place_refactor(tmp_path, files):
    """Write `files` (one holding the markers); return (path, cursor, until)."""
    target = None
    written = {}
    for rel, text in files.items():
        if MARK in text:
            assert target is None, "more than one cursor marker"
            body, cursor, until = split_markers(text)
            written[rel] = body
            target = (rel, cursor, until)
        else:
            written[rel] = text
    assert target is not None, "no <|> cursor marker in project files"
    make_project(tmp_path, written)
    rel, cursor, until = target
    return tmp_path / rel, cursor, until


def refactor_raw(cmd, tmp_path, files, extra=(), project=True):
    """Run a refactoring subcommand on a project; hand back the raw process."""
    path, cursor, until = place_refactor(tmp_path, files)
    args = [cmd, str(path), str(cursor[0]), str(cursor[1])]
    if until is not None:
        args += ["--until", "%d:%d" % until]
    args += list(extra)
    if project:
        args += ["--project", str(tmp_path)]
    return run_raw(args)


def refactor(cmd, tmp_path, files, extra=(), project=True):
    r = refactor_raw(cmd, tmp_path, files, extra, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)


def changed(cmd, tmp_path, files, extra=(), project=True):
    return refactor(cmd, tmp_path, files, extra, project)["changed_files"]


def diff_text(cmd, tmp_path, files, extra=(), project=True):
    r = refactor_raw(cmd, tmp_path, files, tuple(extra) + ("--diff",), project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return r.stdout


def errors_raw(tmp_path, files, rel="main.py", project=True):
    make_project(tmp_path, files)
    args = ["errors", str(tmp_path / rel)]
    if project:
        args += ["--project", str(tmp_path)]
    return run_raw(args)


def syntax_errors(tmp_path, files, rel="main.py", project=True):
    r = errors_raw(tmp_path, files, rel, project)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    return json.loads(r.stdout)["errors"]


def added(diff):
    """Lines added by a unified diff (without the leading '+')."""
    return [ln[1:] for ln in diff.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")]


def removed(diff):
    return [ln[1:] for ln in diff.splitlines()
            if ln.startswith("-") and not ln.startswith("---")]


@pytest.fixture
def rhelpers():
    import types
    return types.SimpleNamespace(
        split_markers=split_markers, place_refactor=place_refactor,
        refactor_raw=refactor_raw, refactor=refactor, changed=changed,
        diff_text=diff_text, errors_raw=errors_raw, syntax_errors=syntax_errors,
        added=added, removed=removed, make_project=make_project,
        run_raw=run_raw, write=write, sith=SITH,
    )
