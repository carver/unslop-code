"""Spec section: Interpreter Mode (--interpreter / --namespaces)."""
import json

from conftest import (interp_complete, interp_defs, interp_raw, item, run_raw,
                      split_cursor, write_namespaces, write_source)


# --- Phrase: "All analysis commands (`complete`, `infer`, `goto`,
#     `signatures`) now accept an `--interpreter` flag with a `--namespaces`
#     argument." — each of the four accepts the pair and still exits 0.
def test_all_four_analysis_commands_accept_the_flags(tmp_path):
    ns = [{"runtime_value": {"type": "int"}}]
    for cmd, key in (("complete", "completions"), ("infer", "definitions"),
                     ("goto", "definitions"), ("signatures", "signatures")):
        proc = interp_raw(tmp_path, "runtime_valu█e\n", cmd, namespaces=ns,
                          name="m_%s.py" % cmd)
        assert proc.returncode == 0, (cmd, proc.stderr)
        assert key in json.loads(proc.stdout)


# --- Phrase: "The `--namespaces` file is a JSON array of objects. Each object
#     represents a namespace. Names are string keys; values are JSON objects
#     describing the runtime value."
def test_namespace_names_become_available(tmp_path):
    ns = [{"alpha": {"type": "int"}, "beta": {"type": "str"}}]
    rows = interp_complete(tmp_path, "x = 1\n█", namespaces=ns)
    names = [r["name"] for r in rows]
    assert "alpha" in names and "beta" in names


# --- Phrase: `type` — "Python type name: `int`, `str`, `list`, `dict`,
#     `function`, `class`, `module`, etc." — reported verbatim as `type`.
def test_type_field_is_preserved_verbatim(tmp_path):
    for typename in ("int", "str", "list", "dict", "function", "class",
                     "module", "MyClass"):
        ns = [{"thing": {"type": typename}}]
        rows = interp_complete(tmp_path, "thin█", namespaces=ns,
                               name="t_%s.py" % typename)
        assert item(rows, "thing")["type"] == typename


# --- Phrase: `value` — "Optional. String representation of the value (for
#     display/docstring)."
def test_value_is_used_as_the_docstring_of_a_runtime_definition(tmp_path):
    ns = [{"total": {"type": "int", "value": "42"}}]
    defs = interp_defs(tmp_path, "tota█l\n", namespaces=ns)
    assert len(defs) == 1
    assert defs[0]["docstring"] == "42"


# --- Phrase: `value` is optional — a namespace entry without it still works.
def test_value_is_optional(tmp_path):
    ns = [{"total": {"type": "int"}}]
    defs = interp_defs(tmp_path, "tota█l\n", namespaces=ns)
    assert len(defs) == 1
    assert defs[0]["docstring"] == ""


# --- Phrase: `module` — "Optional. Module the value originates from."
def test_module_field_feeds_the_full_name(tmp_path):
    ns = [{"loads": {"type": "function", "module": "json"}}]
    defs = interp_defs(tmp_path, "load█s\n", namespaces=ns)
    assert len(defs) == 1
    assert defs[0]["full_name"] == "json.loads"


# --- Phrase: `name` — "Optional. Original name if different from the key."
def test_name_field_is_the_original_name(tmp_path):
    ns = [{"j": {"type": "module", "module": "json", "name": "json"}}]
    defs = interp_defs(tmp_path, "█j\n", namespaces=ns)
    assert len(defs) == 1
    assert defs[0]["name"] == "j"
    # the key names the completion, the `name` field names the value itself
    assert defs[0]["full_name"] == "json"


# --- Phrase: `attributes` — "Optional. Known attributes for classes/modules."
def test_attributes_drive_attribute_completion(tmp_path):
    ns = [{"mod": {"type": "module", "attributes": ["alpha", "beta"]}}]
    rows = interp_complete(tmp_path, "mod.█\n", namespaces=ns)
    names = [r["name"] for r in rows]
    assert "alpha" in names and "beta" in names


# --- Phrase: "1. Static analysis has priority." — a statically known name is
#     described by static analysis, not by the namespace entry.
def test_static_analysis_wins_over_a_namespace_entry(tmp_path):
    ns = [{"value": {"type": "list"}}]
    rows = interp_complete(tmp_path, "value = 1\nvalu█", namespaces=ns)
    row = item(rows, "value")
    assert row["type"] == "instance"
    assert row["description"] != "list (runtime)"


# --- Phrase: "2. Namespace lookup is used only when static analysis cannot
#     resolve a symbol." — infer on a statically resolved name is unaffected.
def test_namespace_is_not_consulted_for_a_resolved_symbol(tmp_path):
    ns = [{"value": {"type": "list"}}]
    defs = interp_defs(tmp_path, "value = 1\nvalu█e\n", namespaces=ns)
    assert [d["description"] for d in defs] != ["list (runtime)"]
    assert all(d["type"] != "list" for d in defs)


# --- Phrase: "3. Namespaces are searched in order (first match wins)."
def test_first_namespace_wins_for_completion(tmp_path):
    ns = [{"shared": {"type": "int"}}, {"shared": {"type": "str"}}]
    rows = interp_complete(tmp_path, "share█", namespaces=ns)
    assert item(rows, "shared")["type"] == "int"


# --- Phrase: "This same first-match rule applies to completion, `infer`, and
#     `goto`: once a runtime-only symbol is satisfied by an earlier namespace
#     object, later namespace objects with the same key must not override it."
def test_first_namespace_wins_for_infer_and_goto(tmp_path):
    ns = [{"shared": {"type": "int"}}, {"shared": {"type": "str"}}]
    for cmd in ("infer", "goto"):
        defs = interp_defs(tmp_path, "share█d\n", cmd=cmd, namespaces=ns,
                           name="fm_%s.py" % cmd)
        assert len(defs) == 1
        assert defs[0]["type"] == "int"
        assert defs[0]["description"] == "int (runtime)"


# --- Phrase: "For completion, names from both static analysis and namespaces
#     are merged."
def test_completion_merges_static_and_runtime_names(tmp_path):
    ns = [{"runtime_only": {"type": "dict"}}]
    rows = interp_complete(tmp_path, "static_only = 1\n█", namespaces=ns)
    names = [r["name"] for r in rows]
    assert "static_only" in names
    assert "runtime_only" in names


# --- Phrase: "For namespace-derived results, `description` is exactly
#     "{type} (runtime)" and `type` is the namespace type string."
def test_runtime_completion_description_and_type(tmp_path):
    ns = [{"cfg": {"type": "dict", "value": "{'a': 1}"}}]
    row = item(interp_complete(tmp_path, "cf█", namespaces=ns), "cfg")
    assert row["type"] == "dict"
    assert row["description"] == "dict (runtime)"


# --- Phrase: "For `infer` and `goto`, namespace-derived fallback definitions
#     also use `description` exactly "{type} (runtime)" and preserve the
#     namespace type string in `type`."
def test_runtime_definition_description_and_type(tmp_path):
    ns = [{"handler": {"type": "function"}}]
    for cmd in ("infer", "goto"):
        defs = interp_defs(tmp_path, "handle█r\n", cmd=cmd, namespaces=ns,
                           name="rd_%s.py" % cmd)
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["description"] == "function (runtime)"
        assert defs[0]["name"] == "handler"


# --- Phrase: "Namespace lookup is used only when static analysis cannot
#     resolve a symbol." — without interpreter mode the same name resolves to
#     nothing at all.
def test_without_interpreter_the_symbol_stays_unresolved(tmp_path):
    defs = interp_defs(tmp_path, "handle█r\n", namespaces=None,
                       interpreter=False)
    assert defs == []


# --- Phrase: "If `--interpreter` is passed without `--namespaces`, the tool
#     behaves identically to normal mode."
def test_interpreter_without_namespaces_matches_normal_mode(tmp_path):
    code = "import os\n\n\ndef f(a):\n    return a\n\n\n█\n"
    with_flag = interp_raw(tmp_path, code, "complete", namespaces=None,
                           interpreter=True, name="a.py")
    plain = interp_raw(tmp_path, code, "complete", namespaces=None,
                       interpreter=False, name="a.py")
    assert with_flag.returncode == 0, with_flag.stderr
    assert with_flag.stdout == plain.stdout


# --- Phrase: the same for `infer` / `goto` / `signatures`.
def test_interpreter_without_namespaces_is_a_no_op_for_every_command(tmp_path):
    code = "def f(a):\n    return a\n\n\nf█(1)\n"
    for cmd in ("infer", "goto", "signatures"):
        with_flag = interp_raw(tmp_path, code, cmd, interpreter=True,
                               name="n_%s.py" % cmd)
        plain = interp_raw(tmp_path, code, cmd, interpreter=False,
                           name="n_%s.py" % cmd)
        assert with_flag.returncode == 0, with_flag.stderr
        assert with_flag.stdout == plain.stdout


# --- Phrase: "If `--namespaces` is provided without `--interpreter`, exit 1
#     with an error message."
def test_namespaces_without_interpreter_is_an_error(tmp_path):
    path = write_namespaces(tmp_path, [{"a": {"type": "int"}}])
    src, line, col = split_cursor("█\n")
    target = write_source(tmp_path, src)
    proc = run_raw("complete", str(target), line, col,
                   "--namespaces", str(path), cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip()


# --- Phrase: "`--namespaces` is invalid unless `--interpreter` is also
#     present." — true for every analysis command.
def test_namespaces_without_interpreter_for_each_command(tmp_path):
    path = write_namespaces(tmp_path, [{"a": {"type": "int"}}])
    target = write_source(tmp_path, "a = 1\n")
    for cmd in ("infer", "goto", "signatures"):
        proc = run_raw(cmd, str(target), 1, 0, "--namespaces", str(path),
                       cwd=str(tmp_path))
        assert proc.returncode == 1, cmd
        assert proc.stdout == ""


# --- Phrase: the namespaces file is read from disk — an unreadable or
#     malformed file is a tool-level failure.
def test_missing_namespaces_file_is_an_error(tmp_path):
    target = write_source(tmp_path, "a = 1\n")
    proc = run_raw("complete", str(target), 1, 0, "--interpreter",
                   "--namespaces", str(tmp_path / "gone.json"),
                   cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_malformed_namespaces_file_is_an_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    target = write_source(tmp_path, "a = 1\n")
    proc = run_raw("complete", str(target), 1, 0, "--interpreter",
                   "--namespaces", str(bad), cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: runtime names take part in prefix matching like any other
#     completion.
def test_runtime_names_are_filtered_by_the_prefix(tmp_path):
    ns = [{"alpha": {"type": "int"}, "beta": {"type": "int"}}]
    rows = interp_complete(tmp_path, "alp█", namespaces=ns)
    names = [r["name"] for r in rows]
    assert "alpha" in names
    assert "beta" not in names


# --- Phrase: "`complete` field" framing still holds for runtime names.
def test_runtime_completion_complete_field(tmp_path):
    ns = [{"alpha": {"type": "int"}}]
    row = item(interp_complete(tmp_path, "alp█", namespaces=ns), "alpha")
    assert row["complete"] == "ha"
    assert set(row) == {"name", "complete", "type", "description"}
