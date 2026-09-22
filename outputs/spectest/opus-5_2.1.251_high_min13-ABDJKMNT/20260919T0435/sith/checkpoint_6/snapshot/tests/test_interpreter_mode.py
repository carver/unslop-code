"""Interpreter mode: the `--interpreter` flag and the `--namespaces` file."""
from conftest import run_cli


# "All analysis commands (`complete`, `infer`, `goto`, `signatures`) now accept an
#  `--interpreter` flag with a `--namespaces` argument"
def test_complete_accepts_interpreter_and_namespaces(complete, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    result = complete("tot|\n", interpreter=True, namespaces=path)
    assert result.returncode == 0


def test_infer_accepts_interpreter_and_namespaces(infer, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    assert infer("tot|al\n", interpreter=True, namespaces=path).returncode == 0


def test_goto_accepts_interpreter_and_namespaces(goto, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    assert goto("tot|al\n", interpreter=True, namespaces=path).returncode == 0


def test_signatures_accepts_interpreter_and_namespaces(signatures, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    source = "def f(a):\n    pass\n\nf(|)\n"
    assert signatures(source, interpreter=True, namespaces=path).returncode == 0


# "The `--namespaces` file is a JSON array of objects. Each object represents a
#  namespace. Names are string keys; values are JSON objects describing the runtime
#  value."
def test_names_from_a_namespace_are_offered(complete, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}, "label": {"type": "str"}}])
    result = complete("|\n", interpreter=True, namespaces=path)
    assert {"total", "label"} <= set(result.names)


def test_every_namespace_object_contributes(complete, namespaces_file):
    path = namespaces_file([{"first": {"type": "int"}}, {"second": {"type": "str"}}])
    result = complete("|\n", interpreter=True, namespaces=path)
    assert {"first", "second"} <= set(result.names)


# "| `type` | string | Python type name: `int`, `str`, `list`, `dict`, `function`,
#  `class`, `module`, etc. |" -- and "`type` is the namespace type string"
def test_completion_type_is_the_namespace_type_string(complete, namespaces_file):
    path = namespaces_file([{"rows": {"type": "list"}, "helper": {"type": "function"}}])
    result = complete("|\n", interpreter=True, namespaces=path)
    assert result.by_name("rows")["type"] == "list"
    assert result.by_name("helper")["type"] == "function"


# "For namespace-derived results, `description` is exactly `\"{type} (runtime)\"`"
def test_completion_description_is_type_runtime(complete, namespaces_file):
    path = namespaces_file([{"rows": {"type": "list"}}])
    result = complete("ro|\n", interpreter=True, namespaces=path)
    assert result.by_name("rows")["description"] == "list (runtime)"


# "| `attributes` | array of string | Optional. Known attributes for classes/modules. |"
def test_attributes_complete_after_a_dot(complete, namespaces_file):
    path = namespaces_file([{"np": {"type": "module", "attributes": ["array", "zeros"]}}])
    result = complete("np.|\n", interpreter=True, namespaces=path)
    assert result.names == ["array", "zeros"]


def test_attribute_prefix_filters_namespace_attributes(complete, namespaces_file):
    path = namespaces_file([{"np": {"type": "module", "attributes": ["array", "zeros"]}}])
    result = complete("np.ar|\n", interpreter=True, namespaces=path)
    assert result.names == ["array"]
    assert result.by_name("array")["complete"] == "ray"


# "| `value` | string | Optional. String representation of the value (for
#  display/docstring). |"
def test_value_becomes_the_docstring_of_a_runtime_definition(infer, namespaces_file):
    path = namespaces_file([{"total": {"type": "int", "value": "42"}}])
    assert infer("tot|al\n", interpreter=True, namespaces=path).only["docstring"] == "42"


# "| `module` | string | Optional. Module the value originates from. |"
# "| `name` | string | Optional. Original name if different from the key. |"
def test_module_and_name_shape_the_full_name(infer, namespaces_file):
    path = namespaces_file([{"dd": {"type": "class", "module": "collections", "name": "deque"}}])
    definition = infer("d|d\n", interpreter=True, namespaces=path).only
    assert definition["name"] == "deque"
    assert definition["full_name"] == "collections.deque"


# "1. Static analysis has priority."
def test_static_analysis_wins_over_a_namespace(infer, namespaces_file):
    path = namespaces_file([{"total": {"type": "str"}}])
    definition = infer("total = 1\ntot|al\n", interpreter=True, namespaces=path).only
    assert definition["full_name"] == "builtins.int"
    assert definition["description"] != "str (runtime)"


def test_static_completion_entry_wins_over_a_namespace(complete, namespaces_file):
    path = namespaces_file([{"helper": {"type": "int"}}])
    result = complete("def helper():\n    pass\n\nhelp|\n", interpreter=True, namespaces=path)
    assert result.by_name("helper")["type"] == "function"
    assert len([c for c in result.completions if c["name"] == "helper"]) == 1


# "2. Namespace lookup is used only when static analysis cannot resolve a symbol."
def test_namespace_answers_what_static_analysis_cannot(infer, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    definition = infer("tot|al\n", interpreter=True, namespaces=path).only
    assert definition["type"] == "int"
    assert definition["description"] == "int (runtime)"


# "For `infer` and `goto`, namespace-derived fallback definitions also use
#  `description` exactly `\"{type} (runtime)\"` and preserve the namespace type string"
def test_goto_reports_the_runtime_definition(goto, namespaces_file):
    path = namespaces_file([{"session": {"type": "class"}}])
    definition = goto("sess|ion\n", interpreter=True, namespaces=path).only
    assert definition["type"] == "class"
    assert definition["description"] == "class (runtime)"
    assert definition["name"] == "session"


# "3. Namespaces are searched in order (first match wins)."
# "once a runtime-only symbol is satisfied by an earlier namespace object, later
#  namespace objects with the same key must not override it"
def test_first_namespace_wins_for_infer(infer, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}, {"total": {"type": "str"}}])
    assert infer("tot|al\n", interpreter=True, namespaces=path).only["type"] == "int"


def test_first_namespace_wins_for_goto(goto, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}, {"total": {"type": "str"}}])
    assert goto("tot|al\n", interpreter=True, namespaces=path).only["type"] == "int"


def test_first_namespace_wins_for_completion(complete, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}, {"total": {"type": "str"}}])
    result = complete("tot|\n", interpreter=True, namespaces=path)
    assert result.by_name("total")["type"] == "int"
    assert len([c for c in result.completions if c["name"] == "total"]) == 1


# "For completion, names from both static analysis and namespaces are merged."
def test_completion_merges_static_and_runtime_names(complete, namespaces_file):
    path = namespaces_file([{"alpha_runtime": {"type": "int"}}])
    source = "alpha_static = 1\nalpha|\n"
    result = complete(source, interpreter=True, namespaces=path)
    assert {"alpha_static", "alpha_runtime"} <= set(result.names)


# "### `--interpreter` Without `--namespaces`": "the tool behaves identically to
#  normal mode."
def test_interpreter_without_namespaces_matches_normal_mode(complete):
    plain = complete("value = 1\nval|\n").completions
    assert complete("value = 1\nval|\n", interpreter=True).completions == plain


def test_interpreter_without_namespaces_infers_normally(infer):
    plain = infer("value = 1\nval|ue\n").definitions
    assert infer("value = 1\nval|ue\n", interpreter=True).definitions == plain


# "### `--namespaces` Without `--interpreter`": "exit 1 with an error message."
def test_namespaces_without_interpreter_is_an_error(complete, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    result = complete("|\n", namespaces=path, expect_ok=False)
    assert result.returncode == 1
    assert result.stderr.strip() != ""
    assert result.stdout == ""


def test_namespaces_without_interpreter_is_an_error_for_goto(goto, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    result = goto("tot|al\n", namespaces=path, expect_ok=False)
    assert result.returncode == 1


# A namespaces file that cannot be read is a request that cannot be answered.
def test_missing_namespaces_file_is_an_error(complete, workdir):
    result = complete(
        "|\n", interpreter=True, namespaces=workdir / "absent.json", expect_ok=False
    )
    assert result.returncode == 1
    assert result.stderr.strip() != ""


def test_namespaces_flag_is_unknown_to_other_commands(workdir, namespaces_file):
    path = namespaces_file([{"total": {"type": "int"}}])
    (workdir / "sample.py").write_text("x = 1\n", encoding="utf-8")
    result = run_cli("names", str(workdir / "sample.py"), "--namespaces", path, cwd=workdir)
    assert result.returncode == 1
