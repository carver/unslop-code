"""Spec: Interpreter Mode."""

from conftest import invoke, write_namespaces, write_source

RUNTIME = [{"data": {"type": "list", "value": "[1, 2, 3]"}}]


# Spec: "All analysis commands (`complete`, `infer`, `goto`, `signatures`) now
# accept an `--interpreter` flag with a `--namespaces` argument"
def test_complete_accepts_interpreter_mode(interpreter):
    result = interpreter("complete", "dat$\n", RUNTIME)
    assert result.code == 0
    assert "data" in result.names


def test_infer_accepts_interpreter_mode(interpreter):
    assert interpreter("infer", "dat$a\n", RUNTIME).code == 0


def test_goto_accepts_interpreter_mode(interpreter):
    assert interpreter("goto", "dat$a\n", RUNTIME).code == 0


def test_signatures_accepts_interpreter_mode(interpreter):
    source = "def add(left):\n    pass\n\nadd($)\n"
    assert interpreter("signatures", source, RUNTIME).code == 0


# Spec: "The `--namespaces` file is a JSON array of objects. Each object
# represents a namespace. Names are string keys; values are JSON objects
# describing the runtime value."
def test_several_namespaces_all_contribute_names(interpreter):
    namespaces = [{"first": {"type": "int"}}, {"second": {"type": "str"}}]
    names = interpreter("complete", "$\n", namespaces).names
    assert {"first", "second"} <= set(names)


# Spec: "`type` | string | Python type name: `int`, `str`, `list`, `dict`,
# `function`, `class`, `module`, etc."
def test_namespace_type_is_reported_verbatim(interpreter):
    namespaces = [{"handler": {"type": "function"}, "count": {"type": "int"}}]
    result = interpreter("complete", "$\n", namespaces)
    assert result.by_name("handler")["type"] == "function"
    assert result.by_name("count")["type"] == "int"


# Spec: "For namespace-derived results, `description` is exactly
# `"{type} (runtime)"` and `type` is the namespace type string."
def test_namespace_completion_description(interpreter):
    result = interpreter("complete", "dat$\n", RUNTIME)
    assert result.by_name("data")["description"] == "list (runtime)"
    assert result.by_name("data")["type"] == "list"


# Spec: "1. Static analysis has priority."
def test_static_analysis_wins_over_a_namespace_entry(interpreter):
    result = interpreter("complete", "value = 1\nvalu$\n", [{"value": {"type": "str"}}])
    assert result.by_name("value")["type"] == "instance"
    assert result.by_name("value")["description"] == "instance of int"


# Spec: "2. Namespace lookup is used only when static analysis cannot resolve
# a symbol."
def test_namespace_is_used_for_a_name_static_analysis_does_not_know(interpreter):
    result = interpreter("complete", "value = 1\n$\n", RUNTIME)
    assert result.by_name("data")["description"] == "list (runtime)"


# Spec: "For completion, names from both static analysis and namespaces are
# merged."
def test_static_and_namespace_names_are_merged(interpreter):
    result = interpreter("complete", "value = 1\n$\n", RUNTIME)
    assert {"value", "data"} <= set(result.names)


# Spec: "3. Namespaces are searched in order (first match wins)."
def test_first_namespace_wins_for_completion(interpreter):
    namespaces = [{"shared": {"type": "int"}}, {"shared": {"type": "str"}}]
    result = interpreter("complete", "shar$\n", namespaces)
    assert result.by_name("shared")["type"] == "int"


# Spec: "once a runtime-only symbol is satisfied by an earlier namespace
# object, later namespace objects with the same key must not override it"
def test_first_namespace_wins_for_infer(interpreter):
    namespaces = [{"shared": {"type": "int"}}, {"shared": {"type": "str"}}]
    assert interpreter("infer", "shar$ed\n", namespaces).only["type"] == "int"


def test_first_namespace_wins_for_goto(interpreter):
    namespaces = [{"shared": {"type": "int"}}, {"shared": {"type": "str"}}]
    assert interpreter("goto", "shar$ed\n", namespaces).only["type"] == "int"


# Spec: "For `infer` and `goto`, namespace-derived fallback definitions also
# use `description` exactly `"{type} (runtime)"` and preserve the namespace
# type string in `type`."
def test_infer_reports_the_runtime_description(interpreter):
    result = interpreter("infer", "dat$a\n", RUNTIME)
    assert result.only["description"] == "list (runtime)"
    assert result.only["type"] == "list"
    assert result.only["name"] == "data"


def test_goto_reports_the_runtime_description(interpreter):
    result = interpreter("goto", "dat$a\n", RUNTIME)
    assert result.only["description"] == "list (runtime)"
    assert result.only["type"] == "list"


# Spec: "2. Namespace lookup is used only when static analysis cannot resolve
# a symbol." - for `infer` the static answer stands alone.
def test_infer_prefers_the_static_definition(interpreter):
    result = interpreter("infer", "value = 1\nvalu$e\n", [{"value": {"type": "str"}}])
    assert [item["name"] for item in result.definitions] == ["int"]


def test_goto_prefers_the_static_definition(interpreter):
    result = interpreter("goto", "value = 1\nvalu$e\n", [{"value": {"type": "str"}}])
    assert result.only["line"] == 1


# Spec: "`value` | string | Optional. String representation of the value (for
# display/docstring)."
def test_value_becomes_the_docstring(interpreter):
    assert interpreter("infer", "dat$a\n", RUNTIME).only["docstring"] == "[1, 2, 3]"


# Spec: "`module` | string | Optional. Module the value originates from."
def test_module_qualifies_the_name(interpreter):
    namespaces = [{"loads": {"type": "function", "module": "json"}}]
    assert interpreter("infer", "load$s\n", namespaces).only["full_name"] == "json.loads"


# Spec: "`name` | string | Optional. Original name if different from the key."
def test_original_name_is_reported(interpreter):
    namespaces = [{"np": {"type": "module", "name": "numpy"}}]
    assert interpreter("infer", "n$p\n", namespaces).only["name"] == "numpy"


# Spec: "`attributes` | array of string | Optional. Known attributes for
# classes/modules."
def test_attributes_complete_after_a_dot(interpreter):
    namespaces = [{"tools": {"type": "module", "attributes": ["load", "dump"]}}]
    result = interpreter("complete", "tools.$\n", namespaces)
    assert set(result.names) == {"load", "dump"}


def test_attributes_are_not_used_when_static_analysis_resolves_the_receiver(interpreter):
    namespaces = [{"helper": {"type": "module", "attributes": ["runtime_only"]}}]
    source = "import helper\nhelper.$\n"
    result = interpreter("complete", source, namespaces, extra={"helper.py": "def written():\n    pass\n"})
    assert result.names == ["written"]


# Spec: "If `--interpreter` is passed without `--namespaces`, the tool behaves
# identically to normal mode."
def test_interpreter_without_namespaces_matches_normal_mode(interpreter, complete):
    source = "value = 1\nvalu$\n"
    assert interpreter("complete", source).stdout == complete(source).stdout


def test_interpreter_without_namespaces_exits_zero(interpreter):
    assert interpreter("infer", "value = 1\nvalu$e\n").code == 0


# Spec: "If `--namespaces` is provided without `--interpreter`, exit 1 with an
# error message."
def test_namespaces_without_interpreter_is_an_error(tmp_path):
    path, line, col = write_source(tmp_path, "value = 1\nvalu$e\n")
    namespaces = write_namespaces(tmp_path, RUNTIME)
    result = invoke("complete", path, line, col, flags=["--namespaces", str(namespaces)])
    assert result.code == 1
    assert result.stderr.strip()
    assert result.stdout == ""


def test_namespaces_without_interpreter_is_an_error_for_goto(tmp_path):
    path, line, col = write_source(tmp_path, "value = 1\nvalu$e\n")
    namespaces = write_namespaces(tmp_path, RUNTIME)
    result = invoke("goto", path, line, col, flags=["--namespaces", str(namespaces)])
    assert result.code == 1


# Spec: the namespaces file has to be readable for interpreter mode to run.
def test_a_missing_namespaces_file_exits_one(tmp_path):
    path, line, col = write_source(tmp_path, "valu$e\n")
    result = invoke(
        "complete", path, line, col,
        flags=["--interpreter", "--namespaces", str(tmp_path / "absent.json")],
    )
    assert result.code == 1
    assert result.stderr.strip()


def test_an_invalid_namespaces_file_exits_one(tmp_path):
    path, line, col = write_source(tmp_path, "valu$e\n")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    result = invoke(
        "complete", path, line, col, flags=["--interpreter", "--namespaces", str(broken)]
    )
    assert result.code == 1


# Spec: "Namespace lookup is used only when static analysis cannot resolve a
# symbol" - a builtin is resolved statically.
def test_builtins_are_not_overridden_by_a_namespace(interpreter):
    result = interpreter("complete", "len$\n", [{"len": {"type": "int"}}])
    assert result.by_name("len")["type"] == "function"
