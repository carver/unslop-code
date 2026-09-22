"""Spec section: Global Settings (`--setting key=value`)."""
import json

from conftest import (CURSOR, item, run_raw, split_cursor, write_config,
                      write_source, write_tree)

C = CURSOR


def run_at(tmp_path, code, cmd="complete", settings=(), name="example.py",
           files=None, project=None, cwd=None):
    write_tree(tmp_path, files or {})
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    args = [cmd, str(path), line, col]
    if cmd == "goto":
        args.append("--follow-imports")
    for value in settings:
        args += ["--setting", value]
    if project is not None:
        args += ["--project", str(project)]
    return run_raw(*args, cwd=cwd or str(tmp_path))


def payload(tmp_path, code, key, **kw):
    proc = run_at(tmp_path, code, **kw)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)[key]


# --- Phrase: "All commands accept zero or more `--setting key=value` flags to
#     override default behavior."
def test_every_command_accepts_settings(tmp_path):
    path = write_source(tmp_path, "def f(a):\n    return a\n\n\nf(1)\n")
    for cmd in ("complete", "infer", "goto", "signatures", "references",
                "context"):
        proc = run_raw(cmd, str(path), 5, 0, "--setting",
                       "case_insensitive=false", cwd=str(tmp_path))
        assert proc.returncode == 0, (cmd, proc.stderr)
    for args in (("names", str(path)), ("search", "f"),
                 ("errors", str(path)), ("env", "list"), ("project", "init")):
        proc = run_raw(*args, "--setting", "add_bracket=true",
                       cwd=str(tmp_path))
        assert proc.returncode == 0, (args, proc.stderr)


# --- Phrase: "zero or more" — several settings at once.
def test_several_settings_at_once(tmp_path):
    rows = payload(tmp_path, "def foo():\n    pass\n\n\nfo" + C + "\n",
                   "completions",
                   settings=["add_bracket=true", "case_insensitive=false"])
    assert item(rows, "foo")["complete"] == "o("


# --- Phrase: `case_insensitive` — "Case-insensitive completion matching."
#     Default true.
def test_case_insensitive_default_is_true(tmp_path):
    rows = payload(tmp_path, "value = 1\nVA" + C + "\n", "completions")
    assert any(r["name"] == "value" for r in rows)


def test_case_insensitive_false_is_case_sensitive(tmp_path):
    rows = payload(tmp_path, "value = 1\nVA" + C + "\n", "completions",
                   settings=["case_insensitive=false"])
    assert not any(r["name"] == "value" for r in rows)


def test_case_insensitive_false_still_matches_exact_case(tmp_path):
    rows = payload(tmp_path, "value = 1\nva" + C + "\n", "completions",
                   settings=["case_insensitive=false"])
    assert any(r["name"] == "value" for r in rows)


# --- Phrase: `dynamic_params` — "Infer parameter types from call sites."
#     Default true.
def test_dynamic_params_default_is_true(tmp_path):
    code = "def f(a):\n    return " + C + "a\n\n\nf(3)\n"
    defs = payload(tmp_path, code, "definitions", cmd="infer")
    assert [d["name"] for d in defs] == ["int"]


def test_dynamic_params_false_disables_call_site_inference(tmp_path):
    code = "def f(a):\n    return " + C + "a\n\n\nf(3)\n"
    defs = payload(tmp_path, code, "definitions", cmd="infer",
                   settings=["dynamic_params=false"])
    assert [d["name"] for d in defs] != ["int"]


# --- Phrase: `smart_sys_path` — "Auto-detect sys.path entries." Default true.
def test_smart_sys_path_default_resolves_siblings(tmp_path):
    defs = payload(tmp_path, "from sibling import A\n" + C + "A\n",
                   "definitions", cmd="goto", name="main.py",
                   files={"sibling.py": "A = 1\n"})
    assert any(d["module_path"] == "sibling.py" for d in defs)


def test_smart_sys_path_false_stops_resolution(tmp_path):
    defs = payload(tmp_path, "from sibling import A\n" + C + "A\n",
                   "definitions", cmd="goto", name="main.py",
                   files={"sibling.py": "A = 1\n"},
                   settings=["smart_sys_path=false"])
    assert all(d["module_path"] != "sibling.py" for d in defs)


# --- Phrase: `add_bracket` — "Append `(` to function/class completions in the
#     `complete` field." Default false.
def test_add_bracket_default_is_false(tmp_path):
    rows = payload(tmp_path, "def foo():\n    pass\n\n\nfo" + C + "\n",
                   "completions")
    assert item(rows, "foo")["complete"] == "o"


def test_add_bracket_true_for_a_function(tmp_path):
    rows = payload(tmp_path, "def foo():\n    pass\n\n\nfo" + C + "\n",
                   "completions", settings=["add_bracket=true"])
    row = item(rows, "foo")
    assert row["complete"] == "o("
    assert row["name"] == "foo"


def test_add_bracket_true_for_a_class(tmp_path):
    rows = payload(tmp_path, "class Foo:\n    pass\n\n\nFo" + C + "\n",
                   "completions", settings=["add_bracket=true"])
    assert item(rows, "Foo")["complete"] == "o("


def test_add_bracket_leaves_other_types_alone(tmp_path):
    rows = payload(tmp_path, "value = 1\nva" + C + "\n", "completions",
                   settings=["add_bracket=true"])
    assert item(rows, "value")["complete"] == "lue"


# --- Phrase: "Boolean settings accept `true`/`false` (case-insensitive)."
def test_boolean_values_are_case_insensitive(tmp_path):
    for text in ("TRUE", "True", "true"):
        rows = payload(tmp_path, "def foo():\n    pass\n\n\nfo" + C + "\n",
                       "completions", settings=["add_bracket=%s" % text])
        assert item(rows, "foo")["complete"] == "o("
    for text in ("FALSE", "False", "false"):
        rows = payload(tmp_path, "def foo():\n    pass\n\n\nfo" + C + "\n",
                       "completions", settings=["add_bracket=%s" % text])
        assert item(rows, "foo")["complete"] == "o"


# --- Phrase: "Invalid setting names or values: exit 1."
def test_invalid_setting_name(tmp_path):
    proc = run_at(tmp_path, "x = 1\n" + C, settings=["nonsense=true"])
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip()


def test_invalid_setting_value(tmp_path):
    proc = run_at(tmp_path, "x = 1\n" + C, settings=["add_bracket=maybe"])
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_setting_without_equals_sign(tmp_path):
    proc = run_at(tmp_path, "x = 1\n" + C, settings=["add_bracket"])
    assert proc.returncode == 1


def test_setting_requires_an_argument(tmp_path):
    path = write_source(tmp_path, "x = 1\n")
    proc = run_raw("complete", str(path), 1, 0, "--setting",
                   cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: "Settings from `--setting` override project config, which
#     overrides defaults."
def test_cli_setting_overrides_project_config(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    defs = payload(tmp_path, "from sibling import A\n" + C + "A\n",
                   "definitions", cmd="goto", name="main.py",
                   files={"sibling.py": "A = 1\n"},
                   settings=["smart_sys_path=true"])
    assert any(d["module_path"] == "sibling.py" for d in defs)


def test_project_config_overrides_the_default(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    defs = payload(tmp_path, "from sibling import A\n" + C + "A\n",
                   "definitions", cmd="goto", name="main.py",
                   files={"sibling.py": "A = 1\n"})
    assert all(d["module_path"] != "sibling.py" for d in defs)


# --- Phrase: settings combine with interpreter mode — a runtime function
#     completion also gets the bracket.
def test_add_bracket_applies_to_runtime_names(tmp_path):
    ns = tmp_path / "ns.json"
    ns.write_text(json.dumps([{"runner": {"type": "function"}}]),
                  encoding="utf-8")
    src, line, col = split_cursor("runn" + C + "\n")
    path = write_source(tmp_path, src, "example.py")
    proc = run_raw("complete", str(path), line, col, "--interpreter",
                   "--namespaces", str(ns), "--setting", "add_bracket=true",
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)["completions"]
    assert item(rows, "runner")["complete"] == "er("
