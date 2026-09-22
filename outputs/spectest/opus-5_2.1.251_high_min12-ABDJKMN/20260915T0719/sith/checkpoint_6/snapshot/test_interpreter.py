"""Interpreter mode -- spec: "Interpreter Mode" (`--interpreter` / `--namespaces`).

Each section quotes the spec phrase it pins down; where the spec leaves room the
matching AMBIGUITIES.md entry (T91+) is named.
"""

import json

import pytest

from conftest import (find, icomplete, iinfer, igoto, irun, ns_file, one,
                      prun, run_raw, split_cursor, write)


NS_X = [{"x": {"type": "int", "value": "42"}}]


# =====================================================================
# "All analysis commands (`complete`, `infer`, `goto`, `signatures`) now
#  accept an `--interpreter` flag with a `--namespaces` argument"
# =====================================================================

@pytest.mark.parametrize("cmd,key", [("complete", "completions"),
                                     ("infer", "definitions"),
                                     ("goto", "definitions"),
                                     ("signatures", "signatures")])
def test_every_analysis_command_accepts_interpreter_and_namespaces(
        tmp_path, cmd, key):
    files = {"main.py": "x = 1\nx<|>\n"}
    r = irun(cmd, tmp_path, files, namespaces=NS_X)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert key in json.loads(r.stdout)


# Context: the `--namespaces=<file>` spelling is accepted too.
def test_namespaces_equals_spelling(tmp_path):
    p = write(tmp_path, "value<|>\n".replace("<|>", ""), "main.py")
    nsp = ns_file(tmp_path, [{"value": {"type": "str"}}])
    r = run_raw(["complete", str(p), "1", "5", "--interpreter",
                 "--namespaces=%s" % nsp])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# =====================================================================
# "The `--namespaces` file is a JSON array of objects. Each object
#  represents a namespace. Names are string keys; values are JSON objects
#  describing the runtime value." (T91)
# =====================================================================

def test_namespace_object_maps_names_to_descriptors(tmp_path):
    files = {"main.py": "<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"alpha": {"type": "int"}, "beta": {"type": "str"}}])
    assert find(comps, "alpha") is not None
    assert find(comps, "beta") is not None


def test_several_namespace_objects_all_contribute(tmp_path):
    files = {"main.py": "<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"alpha": {"type": "int"}}, {"beta": {"type": "str"}}])
    assert find(comps, "alpha")["type"] == "int"
    assert find(comps, "beta")["type"] == "str"


# "| `type` | string | Python type name: `int`, `str`, `list`, `dict`,
#  `function`, `class`, `module`, etc. |"
@pytest.mark.parametrize("tp", ["int", "str", "list", "dict", "function",
                                "class", "module", "MyClass"])
def test_namespace_type_string_is_preserved_verbatim(tmp_path, tp):
    files = {"main.py": "<|>\n"}
    comps = icomplete(tmp_path, files, [{"thing": {"type": tp}}])
    assert find(comps, "thing")["type"] == tp


# "| `value` | string | Optional. String representation of the value
#  (for display/docstring). |" (T93)
def test_value_is_reported_as_the_docstring(tmp_path):
    files = {"main.py": "thin<|>g\n"}
    d = one(iinfer(tmp_path, files, [{"thing": {"type": "int", "value": "42"}}]))
    assert d["docstring"] == "42"


# "| `module` | string | Optional. Module the value originates from. |" (T93)
def test_module_field_feeds_the_full_name(tmp_path):
    files = {"main.py": "arr<|>ay\n"}
    d = one(iinfer(tmp_path, files,
                   [{"array": {"type": "function", "module": "numpy"}}]))
    assert d["full_name"] == "numpy.array"


# "| `name` | string | Optional. Original name if different from the key. |" (T93)
def test_original_name_overrides_the_key_in_definitions(tmp_path):
    files = {"main.py": "n<|>p\n"}
    d = one(iinfer(tmp_path, files,
                   [{"np": {"type": "module", "name": "numpy"}}]))
    assert d["name"] == "numpy"


def test_completion_still_offers_the_key_not_the_original_name(tmp_path):
    files = {"main.py": "n<|>\n"}
    comps = icomplete(tmp_path, files, [{"np": {"type": "module",
                                                "name": "numpy"}}])
    assert find(comps, "np") is not None
    assert find(comps, "numpy") is None


# "| `attributes` | array of string | Optional. Known attributes for
#  classes/modules. |" (T94)
def test_attributes_drive_attribute_completion(tmp_path):
    files = {"main.py": "np.<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"np": {"type": "module",
                               "attributes": ["array", "zeros"]}}])
    assert [c["name"] for c in comps] == ["array", "zeros"]


def test_attribute_completions_are_marked_runtime(tmp_path):
    files = {"main.py": "np.ar<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"np": {"type": "module",
                               "attributes": ["array", "zeros"]}}])
    assert [c["name"] for c in comps] == ["array"]
    assert comps[0]["description"].endswith("(runtime)")


def test_attribute_completion_completes_the_remainder(tmp_path):
    files = {"main.py": "np.ar<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"np": {"type": "module", "attributes": ["array"]}}])
    assert comps[0]["complete"] == "ray"


# =====================================================================
# "1. Static analysis has priority."
# "2. Namespace lookup is used only when static analysis cannot resolve a
#     symbol." (T96)
# =====================================================================

def test_static_binding_wins_over_a_namespace_entry_of_the_same_name(tmp_path):
    files = {"main.py": "x = 'hello'\nx<|>\n"}
    comps = icomplete(tmp_path, files, [{"x": {"type": "int"}}])
    entries = [c for c in comps if c["name"] == "x"]
    assert len(entries) == 1
    assert entries[0]["type"] == "instance"
    assert entries[0]["description"] == "instance of str"


def test_static_definition_wins_for_infer(tmp_path):
    files = {"main.py": "x = 'hello'\nx<|>\n"}
    got = iinfer(tmp_path, files, [{"x": {"type": "int"}}])
    assert [d["name"] for d in got] == ["str"]
    assert all("(runtime)" not in d["description"] for d in got)


def test_static_definition_wins_for_goto(tmp_path):
    files = {"main.py": "x = 'hello'\nx<|>\n"}
    d = one(igoto(tmp_path, files, [{"x": {"type": "int"}}]))
    assert d["line"] == 1 and d["module_path"] == "main.py"


def test_builtins_are_static_so_namespaces_do_not_shadow_them(tmp_path):
    files = {"main.py": "le<|>\n"}
    comps = icomplete(tmp_path, files, [{"len": {"type": "int"}}])
    entries = [c for c in comps if c["name"] == "len"]
    assert len(entries) == 1
    assert entries[0]["type"] == "function"


def test_namespace_fills_in_what_static_analysis_cannot_resolve(tmp_path):
    files = {"main.py": "dat<|>\n"}
    comps = icomplete(tmp_path, files, [{"data": {"type": "list"}}])
    assert find(comps, "data")["type"] == "list"


# =====================================================================
# "Namespaces are searched in order (first match wins)."
# "once a runtime-only symbol is satisfied by an earlier namespace object,
#  later namespace objects with the same key must not override it"
# =====================================================================

def test_first_namespace_wins_for_completion(tmp_path):
    files = {"main.py": "du<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"dup": {"type": "int"}}, {"dup": {"type": "str"}}])
    entries = [c for c in comps if c["name"] == "dup"]
    assert len(entries) == 1
    assert entries[0]["type"] == "int"


def test_first_namespace_wins_for_infer(tmp_path):
    files = {"main.py": "du<|>p\n"}
    d = one(iinfer(tmp_path, files,
                   [{"dup": {"type": "int"}}, {"dup": {"type": "str"}}]))
    assert d["type"] == "int"


def test_first_namespace_wins_for_goto(tmp_path):
    files = {"main.py": "du<|>p\n"}
    d = one(igoto(tmp_path, files,
                  [{"dup": {"type": "int"}}, {"dup": {"type": "str"}}]))
    assert d["type"] == "int"


# =====================================================================
# "For completion, names from both static analysis and namespaces are merged."
# =====================================================================

def test_static_and_runtime_names_are_merged(tmp_path):
    files = {"main.py": "value_static = 1\nvalue_<|>\n"}
    comps = icomplete(tmp_path, files, [{"value_runtime": {"type": "int"}}])
    assert [c["name"] for c in comps] == ["value_runtime", "value_static"]


def test_merged_names_keep_the_normal_ordering_rules(tmp_path):
    files = {"main.py": "abc = 1\n<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"zed": {"type": "int"}, "_hidden": {"type": "int"}}])
    order = [c["name"] for c in comps]
    assert order.index("abc") < order.index("zed") < order.index("_hidden")


def test_runtime_names_honour_the_prefix(tmp_path):
    files = {"main.py": "ru<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"runtime_one": {"type": "int"},
                        "other": {"type": "int"}}])
    assert find(comps, "runtime_one") is not None
    assert find(comps, "other") is None


def test_runtime_completion_fills_the_complete_field(tmp_path):
    files = {"main.py": "ru<|>\n"}
    comps = icomplete(tmp_path, files, [{"runtime_one": {"type": "int"}}])
    assert find(comps, "runtime_one")["complete"] == "ntime_one"


# =====================================================================
# "For namespace-derived results, `description` is exactly `"{type} (runtime)"`
#  and `type` is the namespace type string."
# =====================================================================

@pytest.mark.parametrize("tp", ["int", "str", "list", "function", "module"])
def test_completion_description_is_type_space_runtime(tmp_path, tp):
    files = {"main.py": "thi<|>\n"}
    comps = icomplete(tmp_path, files, [{"thing": {"type": tp}}])
    item = find(comps, "thing")
    assert item["description"] == "%s (runtime)" % tp
    assert item["type"] == tp


# "For `infer` and `goto`, namespace-derived fallback definitions also use
#  `description` exactly `"{type} (runtime)"` and preserve the namespace type
#  string in `type`."
@pytest.mark.parametrize("cmd", ["infer", "goto"])
@pytest.mark.parametrize("tp", ["int", "list", "function"])
def test_definition_description_is_type_space_runtime(tmp_path, cmd, tp):
    files = {"main.py": "thi<|>ng\n"}
    fn = iinfer if cmd == "infer" else igoto
    d = one(fn(tmp_path, files, [{"thing": {"type": tp}}]))
    assert d["description"] == "%s (runtime)" % tp
    assert d["type"] == tp


# T93: a runtime value has no file and no position.
@pytest.mark.parametrize("cmd", ["infer", "goto"])
def test_runtime_definition_has_no_file_or_position(tmp_path, cmd):
    files = {"main.py": "thi<|>ng\n"}
    fn = iinfer if cmd == "infer" else igoto
    d = one(fn(tmp_path, files, [{"thing": {"type": "int"}}]))
    assert d["module_path"] == "" and d["line"] == 0 and d["column"] == 0


def test_runtime_definition_name_defaults_to_the_key(tmp_path):
    files = {"main.py": "thi<|>ng\n"}
    d = one(iinfer(tmp_path, files, [{"thing": {"type": "int"}}]))
    assert d["name"] == "thing"


def test_runtime_definition_full_name_without_module(tmp_path):
    files = {"main.py": "thi<|>ng\n"}
    d = one(igoto(tmp_path, files, [{"thing": {"type": "int"}}]))
    assert d["full_name"] == "thing"


# T94: `infer` through a runtime-only receiver's attributes.
def test_infer_on_a_runtime_attribute(tmp_path):
    files = {"main.py": "np.arr<|>ay\n"}
    got = iinfer(tmp_path, files,
                 [{"np": {"type": "module", "attributes": ["array"]}}])
    assert len(got) == 1
    assert got[0]["name"] == "array"
    assert got[0]["description"].endswith("(runtime)")


def test_unknown_runtime_attribute_yields_nothing(tmp_path):
    files = {"main.py": "np.miss<|>ing\n"}
    assert iinfer(tmp_path, files,
                  [{"np": {"type": "module", "attributes": ["array"]}}]) == []


# =====================================================================
# "### `--interpreter` Without `--namespaces`
#  If `--interpreter` is passed without `--namespaces`, the tool behaves
#  identically to normal mode."
# =====================================================================

@pytest.mark.parametrize("cmd,key", [("complete", "completions"),
                                     ("infer", "definitions"),
                                     ("goto", "definitions"),
                                     ("signatures", "signatures")])
def test_interpreter_without_namespaces_matches_normal_mode(tmp_path, cmd, key):
    src = {"main.py": "x = 1\ndef f(a, b):\n    return a\n\nf(x<|>, 2)\n"}
    plain = prun(cmd, tmp_path, dict(src))
    interp = irun(cmd, tmp_path, dict(src))
    assert plain.returncode == 0 and interp.returncode == 0
    assert json.loads(plain.stdout) == json.loads(interp.stdout)


def test_interpreter_without_namespaces_finds_no_runtime_names(tmp_path):
    files = {"main.py": "dat<|>\n"}
    r = irun("complete", tmp_path, files)
    comps = json.loads(r.stdout)["completions"]
    assert find(comps, "data") is None


# =====================================================================
# "### `--namespaces` Without `--interpreter`
#  If `--namespaces` is provided without `--interpreter`, exit 1 with an error
#  message."
# =====================================================================

@pytest.mark.parametrize("cmd", ["complete", "infer", "goto", "signatures"])
def test_namespaces_without_interpreter_exits_1(tmp_path, cmd):
    files = {"main.py": "x = 1\nx<|>\n"}
    r = irun(cmd, tmp_path, files, namespaces=NS_X, interpreter=False)
    assert r.returncode == 1
    assert r.stderr.strip()


def test_namespaces_without_interpreter_prints_no_payload(tmp_path):
    files = {"main.py": "x = 1\nx<|>\n"}
    r = irun("complete", tmp_path, files, namespaces=NS_X, interpreter=False)
    assert r.stdout.strip() == ""


# =====================================================================
# Bad namespace files (T92)
# =====================================================================

def test_missing_namespaces_file_exits_1(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run_raw(["complete", str(p), "1", "1", "--interpreter",
                 "--namespaces", str(tmp_path / "nope.json")])
    assert r.returncode == 1 and r.stderr.strip()


def test_malformed_namespaces_file_exits_1(tmp_path):
    p = write(tmp_path, "x = 1\n")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    r = run_raw(["complete", str(p), "1", "1", "--interpreter",
                 "--namespaces", str(bad)])
    assert r.returncode == 1 and r.stderr.strip()


def test_namespaces_file_must_hold_an_array(tmp_path):
    p = write(tmp_path, "x = 1\n")
    bad = tmp_path / "obj.json"
    bad.write_text(json.dumps({"x": {"type": "int"}}), encoding="utf-8")
    r = run_raw(["complete", str(p), "1", "1", "--interpreter",
                 "--namespaces", str(bad)])
    assert r.returncode == 1 and r.stderr.strip()


# T118: an entry without a usable `type` cannot produce "{type} (runtime)".
def test_entry_without_a_type_is_skipped(tmp_path):
    files = {"main.py": "thi<|>\n"}
    comps = icomplete(tmp_path, files, [{"thing": {"value": "42"}}])
    assert find(comps, "thing") is None


def test_non_object_entry_is_skipped(tmp_path):
    files = {"main.py": "thi<|>\n"}
    comps = icomplete(tmp_path, files, [{"thing": "int"}])
    assert find(comps, "thing") is None


# =====================================================================
# T95: `signatures` accepts the flags but namespaces add no signature.
# =====================================================================

def test_signatures_of_a_runtime_only_callable_is_empty(tmp_path):
    files = {"main.py": "helper(<|>)\n"}
    sigs = json.loads(irun("signatures", tmp_path, files,
                           [{"helper": {"type": "function"}}]).stdout)
    assert sigs["signatures"] == []


def test_signatures_still_work_for_static_callables_in_interpreter_mode(tmp_path):
    files = {"main.py": "def f(a, b):\n    return a\n\nf(<|>)\n"}
    sigs = json.loads(irun("signatures", tmp_path, files,
                           [{"f": {"type": "function"}}]).stdout)["signatures"]
    assert [s["name"] for s in sigs] == ["f"]
    assert sigs[0]["params"] == ["a", "b"]


# =====================================================================
# T97: the flags are inert, not an error, on the other commands.
# =====================================================================

def test_interpreter_is_accepted_by_references(tmp_path):
    files = {"main.py": "x = 1\nx<|>\n"}
    r = irun("references", tmp_path, files, namespaces=NS_X)
    assert r.returncode == 0, "stderr=%r" % r.stderr


# =====================================================================
# T96: a name bound to an import static analysis cannot resolve is exactly
# the case "static analysis cannot resolve a symbol" describes.
# =====================================================================

def test_unresolvable_import_falls_back_to_runtime_attributes(tmp_path):
    files = {"main.py": "import numpy_not_installed as np\nnp.<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"np": {"type": "module", "attributes": ["array"]}}])
    assert find(comps, "array") is not None


def test_a_resolvable_receiver_is_not_overridden(tmp_path):
    files = {"main.py": "class C:\n    thing = 1\nc = C()\nc.<|>\n"}
    comps = icomplete(tmp_path, files,
                      [{"c": {"type": "module", "attributes": ["runtime_only"]}}])
    assert find(comps, "thing") is not None
    assert find(comps, "runtime_only") is None


def test_goto_through_an_unresolvable_import(tmp_path):
    files = {"main.py": "import numpy_not_installed as np\nnp.arr<|>ay\n"}
    got = igoto(tmp_path, files,
                [{"np": {"type": "module", "attributes": ["array"]}}])
    assert [d["name"] for d in got] == ["array"]
