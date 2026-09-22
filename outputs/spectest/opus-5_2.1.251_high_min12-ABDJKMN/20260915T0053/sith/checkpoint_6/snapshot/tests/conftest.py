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


# --- project helpers (multi-file spec) -------------------------------------

def write_tree(tmp_path, files):
    """Create every `relative path -> source` entry under `tmp_path`."""
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def run_cmd(cmd, path, line, col, project=None, follow=False, fuzzy=False,
            cwd=None):
    args = [cmd, str(path), line, col]
    if fuzzy:
        args.append("--fuzzy")
    if follow:
        args.append("--follow-imports")
    if project is not None:
        args += ["--project", str(project)]
    return run_raw(*args, cwd=cwd)


def in_project(tmp_path, files, cmd, project=None, follow=False, fuzzy=False,
               cwd=None):
    """Write a whole project; run `cmd` at the CURSOR in the one marked file."""
    marked = [n for n, c in files.items() if CURSOR in c]
    assert len(marked) == 1, "exactly one file must carry the cursor marker"
    target = marked[0]
    plain = {}
    line = col = None
    for name, content in files.items():
        if name == target:
            content, line, col = split_cursor(content)
        plain[name] = content
    write_tree(tmp_path, plain)
    return run_cmd(cmd, tmp_path / target, line, col, project=project,
                   follow=follow, fuzzy=fuzzy, cwd=cwd or str(tmp_path))


def defs_in(tmp_path, files, cmd="goto", project=None, follow=False, cwd=None):
    proc = in_project(tmp_path, files, cmd, project=project, follow=follow,
                      cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"definitions"}
    return data["definitions"]


def comps_in(tmp_path, files, project=None, fuzzy=False, cwd=None):
    proc = in_project(tmp_path, files, "complete", project=project,
                      fuzzy=fuzzy, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- new-subcommand helpers (signatures / references / search / names) ------

def run_sig(path, line, col, project=None, cwd=None):
    args = ["signatures", str(path), line, col]
    if project is not None:
        args += ["--project", str(project)]
    return run_raw(*args, cwd=cwd)


def sig_raw(tmp_path, code, name="example.py", extra=None):
    return _at(tmp_path, code, "signatures", name=name, extra=extra)


def sigs_at(tmp_path, code, name="example.py", extra=None):
    """Run `signatures`; assert exit 0 and return the `signatures` list."""
    proc = sig_raw(tmp_path, code, name=name, extra=extra)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"signatures"}
    return data["signatures"]


def sigs_in(tmp_path, files, project=None, cwd=None):
    proc = in_project(tmp_path, files, "signatures", project=project, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"signatures"}
    return data["signatures"]


def refs_raw(tmp_path, code, name="example.py", extra=None, scope=None):
    for fname, content in (extra or {}).items():
        target = tmp_path / fname
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    args = ["references", str(path), line, col]
    if scope is not None:
        args += ["--scope", scope]
    return run_raw(*args, cwd=str(tmp_path))


def refs_at(tmp_path, code, name="example.py", extra=None, scope=None):
    proc = refs_raw(tmp_path, code, name=name, extra=extra, scope=scope)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"references"}
    return data["references"]


def refs_in(tmp_path, files, scope=None, project=None, cwd=None):
    marked = [n for n, c in files.items() if CURSOR in c]
    assert len(marked) == 1, "exactly one file must carry the cursor marker"
    target = marked[0]
    plain = {}
    line = col = None
    for fname, content in files.items():
        if fname == target:
            content, line, col = split_cursor(content)
        plain[fname] = content
    write_tree(tmp_path, plain)
    args = ["references", str(tmp_path / target), line, col]
    if scope is not None:
        args += ["--scope", scope]
    if project is not None:
        args += ["--project", str(project)]
    proc = run_raw(*args, cwd=cwd or str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"references"}
    return data["references"]


def places(references):
    return [(r["module_path"], r["line"], r["column"]) for r in references]


def search_in(tmp_path, files, query, project=None, cwd=None):
    write_tree(tmp_path, files)
    args = ["search", query]
    if project is not None:
        args += ["--project", str(project)]
    proc = run_raw(*args, cwd=cwd or str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"results"}
    return data["results"]


def names_in_file(tmp_path, files, target, all_scopes=False, project=None,
                  cwd=None):
    write_tree(tmp_path, files)
    args = ["names", str(tmp_path / target)]
    if all_scopes:
        args.append("--all-scopes")
    if project is not None:
        args += ["--project", str(project)]
    proc = run_raw(*args, cwd=cwd or str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"names"}
    return data["names"]


# --- refactoring helpers (rename / inline / extract-* / errors) -------------

def _marked(files):
    """Split a project dict on its single CURSOR marker.

    Returns (target_name, files_without_marker, line, col).
    """
    marked = [n for n, c in files.items() if CURSOR in c]
    assert len(marked) == 1, "exactly one file must carry the cursor marker"
    target = marked[0]
    plain = {}
    line = col = None
    for name, content in files.items():
        if name == target:
            content, line, col = split_cursor(content)
        plain[name] = content
    return target, plain, line, col


def refactor_raw(tmp_path, files, cmd, extra=(), project=None, cwd=None,
                 diff=False):
    """Write a whole project and run a refactoring command at the cursor."""
    target, plain, line, col = _marked(files)
    write_tree(tmp_path, plain)
    args = [cmd, str(tmp_path / target), line, col, *extra]
    if diff:
        args.append("--diff")
    if project is not None:
        args += ["--project", str(project)]
    return run_raw(*args, cwd=cwd or str(tmp_path))


def refactor_in(tmp_path, files, cmd, extra=(), project=None, cwd=None):
    """Run a refactoring command; assert exit 0 and return the JSON object."""
    proc = refactor_raw(tmp_path, files, cmd, extra=extra, project=project,
                        cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def rename_raw(tmp_path, files, new_name, diff=False, project=None, cwd=None):
    return refactor_raw(tmp_path, files, "rename",
                        extra=["--new-name", new_name], diff=diff,
                        project=project, cwd=cwd)


def rename_in(tmp_path, files, new_name, project=None, cwd=None):
    proc = rename_raw(tmp_path, files, new_name, project=project, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def inline_raw(tmp_path, files, diff=False, project=None, cwd=None):
    return refactor_raw(tmp_path, files, "inline", diff=diff, project=project,
                        cwd=cwd)


def inline_in(tmp_path, files, project=None, cwd=None):
    proc = inline_raw(tmp_path, files, project=project, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def extract_var_raw(tmp_path, files, until, name, diff=False, project=None,
                    cwd=None):
    return refactor_raw(tmp_path, files, "extract-variable",
                        extra=["--until", until, "--name", name], diff=diff,
                        project=project, cwd=cwd)


def extract_var_in(tmp_path, files, until, name, project=None, cwd=None):
    proc = extract_var_raw(tmp_path, files, until, name, project=project,
                           cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def extract_fn_raw(tmp_path, files, until, name, diff=False, project=None,
                   cwd=None):
    return refactor_raw(tmp_path, files, "extract-function",
                        extra=["--until", until, "--name", name], diff=diff,
                        project=project, cwd=cwd)


def extract_fn_in(tmp_path, files, until, name, project=None, cwd=None):
    proc = extract_fn_raw(tmp_path, files, until, name, project=project,
                          cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def changed(data):
    """The `changed_files` map of a refactoring payload."""
    assert "changed_files" in data, data
    return data["changed_files"]


def only_file(data, name="example.py"):
    """The new content of the single changed file."""
    files = changed(data)
    assert list(files) == [name], files
    return files[name]


def errors_raw(tmp_path, code, name="broken.py", cwd=None):
    path = write_source(tmp_path, code, name)
    return run_raw("errors", str(path), cwd=cwd or str(tmp_path))


def errors_at(tmp_path, code, name="broken.py", cwd=None):
    proc = errors_raw(tmp_path, code, name=name, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"errors"}
    return data["errors"]


# --- interpreter-mode helpers ----------------------------------------------

def write_namespaces(tmp_path, namespaces, name="ns.json"):
    """Write a `--namespaces` JSON file (a list of name -> descriptor maps)."""
    path = tmp_path / name
    path.write_text(json.dumps(namespaces), encoding="utf-8")
    return path


def interp_raw(tmp_path, code, cmd, namespaces=None, interpreter=True,
               name="example.py", extra=None, project=None, settings=()):
    """Run `cmd` at the cursor with interpreter mode wired up."""
    for fname, content in (extra or {}).items():
        target = tmp_path / fname
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    args = [cmd, str(path), line, col]
    if interpreter:
        args.append("--interpreter")
    if namespaces is not None:
        args += ["--namespaces", str(write_namespaces(tmp_path, namespaces))]
    if project is not None:
        args += ["--project", str(project)]
    for item in settings:
        args += ["--setting", item]
    return run_raw(*args, cwd=str(tmp_path))


def interp_json(tmp_path, code, cmd, key, **kw):
    proc = interp_raw(tmp_path, code, cmd, **kw)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {key}, data
    return data[key]


def interp_complete(tmp_path, code, namespaces=None, **kw):
    return interp_json(tmp_path, code, "complete", "completions",
                       namespaces=namespaces, **kw)


def interp_defs(tmp_path, code, cmd="infer", namespaces=None, **kw):
    return interp_json(tmp_path, code, cmd, "definitions",
                       namespaces=namespaces, **kw)


def item(rows, name):
    for row in rows:
        if row["name"] == name:
            return row
    raise AssertionError("%r not among %r" % (name, [r["name"] for r in rows]))


# --- env / project / context helpers ---------------------------------------

def run_json(*args, cwd=None):
    """Run sith.py, assert exit 0, and return the decoded JSON payload."""
    proc = run_raw(*args, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def env_list(cwd=None, *extra):
    return run_json("env", "list", *extra, cwd=cwd)["environments"]


def env_virtualenvs(cwd=None, *extra):
    return run_json("env", "find-virtualenvs", *extra,
                    cwd=cwd)["environments"]


def env_info(executable=None, cwd=None, *extra):
    args = ["env", "info"]
    if executable is not None:
        args.append(str(executable))
    return run_json(*args, *extra, cwd=cwd)


def fake_venv(directory, name, real=None, cfg=True):
    """Create a venv-shaped directory `<directory>/<name>` and return its root.

    `bin/python` is a symlink to a real interpreter, and `pyvenv.cfg` makes the
    interpreter report it as a virtualenv.
    """
    root = directory / name
    (root / "bin").mkdir(parents=True, exist_ok=True)
    os.symlink(real or PY, str(root / "bin" / "python"))
    if cfg:
        (root / "pyvenv.cfg").write_text(
            "home = %s\ninclude-system-site-packages = false\n"
            % os.path.dirname(real or PY), encoding="utf-8")
    return root


def write_config(directory, config):
    """Write `<directory>/.sith/project.json`."""
    sith_dir = directory / ".sith"
    sith_dir.mkdir(parents=True, exist_ok=True)
    path = sith_dir / "project.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def read_config(directory):
    path = directory / ".sith" / "project.json"
    return json.loads(path.read_text(encoding="utf-8"))


def context_raw(tmp_path, code, name="example.py", project=None, cwd=None,
                extra_args=()):
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    args = ["context", str(path), line, col]
    if project is not None:
        args += ["--project", str(project)]
    return run_raw(*args, *extra_args, cwd=cwd or str(tmp_path))


def context_at(tmp_path, code, **kw):
    proc = context_raw(tmp_path, code, **kw)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"context"}, data
    return data["context"]
