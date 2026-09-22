"""`--setting key=value` -- spec: "Global Settings". See AMBIGUITIES.md T114-T117."""

import json

import pytest

from conftest import (find, make_project, pcomplete, prun, run_raw, write,
                      write_config)


DEFAULTS = {"environment_path": "", "sys_path": [], "added_sys_path": [],
            "smart_sys_path": True}


def comps(tmp_path, src, extra=(), project=None, files=None):
    return pcomplete(tmp_path, files or {"main.py": src}, extra, project)


# =====================================================================
# "All commands accept zero or more `--setting key=value` flags"
# =====================================================================

@pytest.mark.parametrize("cmd", ["complete", "infer", "goto", "signatures",
                                 "references", "context"])
def test_cursor_commands_accept_setting(tmp_path, cmd):
    r = prun(cmd, tmp_path, {"main.py": "x = 1\nx<|>\n"},
             extra=["--setting", "case_insensitive=true"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


def test_names_accepts_setting(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run_raw(["names", str(p), "--setting", "add_bracket=true"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


def test_search_accepts_setting(tmp_path):
    make_project(tmp_path, {"main.py": "def thing():\n    pass\n"})
    r = run_raw(["search", "thing", "--project", str(tmp_path),
                 "--setting", "add_bracket=true"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


def test_errors_accepts_setting(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run_raw(["errors", str(p), "--setting", "dynamic_params=false"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


def test_several_settings_at_once(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x = 1\nx<|>\n"},
             extra=["--setting", "add_bracket=true",
                    "--setting", "case_insensitive=false"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# T116: the `--setting=key=value` spelling works too.
def test_equals_spelling(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x = 1\nx<|>\n"},
             extra=["--setting=add_bracket=true"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# "Boolean settings accept `true`/`false` (case-insensitive)."
@pytest.mark.parametrize("value", ["true", "TRUE", "True", "false", "FALSE",
                                   "False"])
def test_boolean_spellings_are_case_insensitive(tmp_path, value):
    r = prun("complete", tmp_path, {"main.py": "x = 1\nx<|>\n"},
             extra=["--setting", "add_bracket=%s" % value])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# "Invalid setting names or values: exit 1."
def test_unknown_setting_name_exits_1(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x<|>\n"},
             extra=["--setting", "not_a_setting=true"])
    assert r.returncode == 1 and r.stderr.strip()


def test_invalid_boolean_value_exits_1(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x<|>\n"},
             extra=["--setting", "add_bracket=maybe"])
    assert r.returncode == 1 and r.stderr.strip()


def test_setting_without_an_equals_sign_exits_1(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x<|>\n"},
             extra=["--setting", "add_bracket"])
    assert r.returncode == 1 and r.stderr.strip()


def test_setting_with_an_empty_value_exits_1(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x<|>\n"},
             extra=["--setting", "add_bracket="])
    assert r.returncode == 1


def test_invalid_setting_prints_no_payload(tmp_path):
    r = prun("complete", tmp_path, {"main.py": "x<|>\n"},
             extra=["--setting", "bogus=true"])
    assert r.stdout.strip() == ""


# =====================================================================
# "| `case_insensitive` | bool | true | Case-insensitive completion matching. |"
# =====================================================================

def test_case_insensitive_is_on_by_default(tmp_path):
    got = comps(tmp_path, "value = 1\nVAL<|>\n")
    assert find(got, "value") is not None


def test_case_insensitive_true_matches_across_case(tmp_path):
    got = comps(tmp_path, "value = 1\nVAL<|>\n",
                extra=["--setting", "case_insensitive=true"])
    assert find(got, "value") is not None


def test_case_insensitive_false_requires_an_exact_prefix(tmp_path):
    got = comps(tmp_path, "value = 1\nVAL<|>\n",
                extra=["--setting", "case_insensitive=false"])
    assert find(got, "value") is None


def test_case_insensitive_false_still_matches_the_right_case(tmp_path):
    got = comps(tmp_path, "value = 1\nval<|>\n",
                extra=["--setting", "case_insensitive=false"])
    assert find(got, "value") is not None


def test_case_insensitive_false_hides_differently_cased_names(tmp_path):
    got = comps(tmp_path, "Value = 1\nval<|>\n",
                extra=["--setting", "case_insensitive=false"])
    assert find(got, "Value") is None


# T115: fuzzy matching is matching too.
def test_case_insensitive_false_applies_to_fuzzy_matching(tmp_path):
    got = comps(tmp_path, "value_total = 1\nVLT<|>\n",
                extra=["--fuzzy", "--setting", "case_insensitive=false"])
    assert find(got, "value_total") is None


def test_fuzzy_matching_is_case_insensitive_by_default(tmp_path):
    got = comps(tmp_path, "value_total = 1\nVLT<|>\n", extra=["--fuzzy"])
    assert find(got, "value_total") is not None


# =====================================================================
# "| `add_bracket` | bool | false | Append `(` to function/class completions in
#  the `complete` field. |"
# =====================================================================

def test_add_bracket_is_off_by_default(tmp_path):
    got = comps(tmp_path, "def helper():\n    pass\nhel<|>\n")
    assert find(got, "helper")["complete"] == "per"


def test_add_bracket_appends_to_a_function(tmp_path):
    got = comps(tmp_path, "def helper():\n    pass\nhel<|>\n",
                extra=["--setting", "add_bracket=true"])
    assert find(got, "helper")["complete"] == "per("


def test_add_bracket_appends_to_a_class(tmp_path):
    got = comps(tmp_path, "class Widget:\n    pass\nWid<|>\n",
                extra=["--setting", "add_bracket=true"])
    assert find(got, "Widget")["complete"] == "get("


def test_add_bracket_leaves_instances_alone(tmp_path):
    got = comps(tmp_path, "value = 1\nval<|>\n",
                extra=["--setting", "add_bracket=true"])
    assert find(got, "value")["complete"] == "ue"


def test_add_bracket_leaves_keywords_alone(tmp_path):
    got = comps(tmp_path, "whi<|>\n", extra=["--setting", "add_bracket=true"])
    assert find(got, "while")["complete"] == "le"


# T114: only `complete` changes.
def test_add_bracket_does_not_change_name_or_description(tmp_path):
    got = comps(tmp_path, "def helper():\n    pass\nhel<|>\n",
                extra=["--setting", "add_bracket=true"])
    item = find(got, "helper")
    assert item["name"] == "helper"
    assert item["description"] == "def helper(...)"


def test_add_bracket_applies_to_attribute_completions(tmp_path):
    files = {"main.py": "class C:\n    def m(self):\n        pass\nC().m<|>\n"}
    got = pcomplete(tmp_path, files, extra=["--setting", "add_bracket=true"])
    assert find(got, "m")["complete"] == "("


def test_add_bracket_applies_to_runtime_completions(tmp_path):
    files = {"main.py": "hel<|>\n"}
    nsp = tmp_path / "ns.json"
    nsp.write_text(json.dumps([{"helper": {"type": "function"}}]))
    got = pcomplete(tmp_path, files,
                    extra=["--interpreter", "--namespaces", str(nsp),
                           "--setting", "add_bracket=true"])
    assert find(got, "helper")["complete"] == "per("


# =====================================================================
# "| `dynamic_params` | bool | true | Infer parameter types from call sites. |"
# =====================================================================

def test_dynamic_params_is_on_by_default(tmp_path):
    files = {"main.py": "def f(a):\n    return <|>a\nf(3)\n"}
    got = prun("infer", tmp_path, files, project=True)
    assert [d["name"] for d in json.loads(got.stdout)["definitions"]] == ["int"]


def test_dynamic_params_false_turns_call_site_inference_off(tmp_path):
    files = {"main.py": "def f(a):\n    return <|>a\nf(3)\n"}
    r = prun("infer", tmp_path, files,
             extra=["--setting", "dynamic_params=false"], project=True)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert json.loads(r.stdout)["definitions"] == []


def test_dynamic_params_true_is_explicit_opt_in(tmp_path):
    files = {"main.py": "def f(a):\n    return <|>a\nf(3)\n"}
    r = prun("infer", tmp_path, files,
             extra=["--setting", "dynamic_params=true"], project=True)
    assert [d["name"] for d in json.loads(r.stdout)["definitions"]] == ["int"]


# =====================================================================
# "| `smart_sys_path` | bool | true | Auto-detect sys.path entries. |"
# =====================================================================

def test_smart_sys_path_setting_false_drops_the_project_root(tmp_path):
    files = {"main.py": "import lib\nlib.<|>\n",
             "lib.py": "class Local:\n    pass\n"}
    got = comps(tmp_path, None, files=files, project=True,
                extra=["--setting", "smart_sys_path=false"])
    assert find(got, "Local") is None


def test_smart_sys_path_setting_true_keeps_the_project_root(tmp_path):
    files = {"main.py": "import lib\nlib.<|>\n",
             "lib.py": "class Local:\n    pass\n"}
    got = comps(tmp_path, None, files=files, project=True,
                extra=["--setting", "smart_sys_path=true"])
    assert find(got, "Local") is not None


# =====================================================================
# "Settings from `--setting` override project config, which overrides defaults."
# =====================================================================

def test_cli_setting_overrides_project_config(tmp_path):
    files = {"main.py": "import lib\nlib.<|>\n",
             "lib.py": "class Local:\n    pass\n"}
    make_project(tmp_path, files)
    write_config(tmp_path, dict(DEFAULTS, smart_sys_path=False))
    got = pcomplete(tmp_path, files, project=True,
                    extra=["--setting", "smart_sys_path=true"])
    assert find(got, "Local") is not None


def test_project_config_overrides_the_default(tmp_path):
    files = {"main.py": "import lib\nlib.<|>\n",
             "lib.py": "class Local:\n    pass\n"}
    make_project(tmp_path, files)
    write_config(tmp_path, dict(DEFAULTS, smart_sys_path=False))
    got = pcomplete(tmp_path, files, project=True)
    assert find(got, "Local") is None


def test_defaults_apply_without_config_or_flags(tmp_path):
    files = {"main.py": "import lib\nlib.<|>\n",
             "lib.py": "class Local:\n    pass\n"}
    got = pcomplete(tmp_path, files, project=True)
    assert find(got, "Local") is not None


def test_last_occurrence_of_a_repeated_setting_wins(tmp_path):
    got = comps(tmp_path, "value = 1\nVAL<|>\n",
                extra=["--setting", "case_insensitive=false",
                       "--setting", "case_insensitive=true"])
    assert find(got, "value") is not None
