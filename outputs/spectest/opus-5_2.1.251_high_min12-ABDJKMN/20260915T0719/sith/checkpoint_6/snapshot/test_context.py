"""`context` -- spec: "New Subcommand: `context`". See AMBIGUITIES.md T112-T113."""

import json

import pytest

from conftest import context, context_raw, make_project, run_raw, write


def ctx(tmp_path, src, extra=(), project=None):
    return context(tmp_path, {"main.py": src}, extra, project)


# =====================================================================
# "python sith.py context <file> <line> <col> [--project <dir>]"
# =====================================================================

def test_context_exits_zero_and_emits_the_context_key(tmp_path):
    r = context_raw(tmp_path, {"main.py": "x = 1<|>\n"})
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert "context" in json.loads(r.stdout)


def test_context_accepts_the_project_flag(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/main.py": "def f():\n    x<|> = 1\n"}
    got = context(tmp_path, files, project=True)
    assert [c["name"] for c in got] == ["f"]


def test_context_rejects_a_missing_file(tmp_path):
    r = run_raw(["context", str(tmp_path / "nope.py"), "1", "0"])
    assert r.returncode == 1


def test_context_rejects_an_out_of_range_line(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run_raw(["context", str(p), "9", "0"])
    assert r.returncode == 1


# =====================================================================
# "If the cursor is at module level, the array is empty."
# =====================================================================

def test_module_level_cursor_gives_an_empty_array(tmp_path):
    assert ctx(tmp_path, "x = 1<|>\n") == []


def test_empty_line_at_module_level(tmp_path):
    assert ctx(tmp_path, "x = 1\n<|>\n") == []


def test_module_level_after_a_function(tmp_path):
    assert ctx(tmp_path, "def f():\n    pass\n\ny = <|>1\n") == []


# =====================================================================
# "Return the scope context at the cursor position -- what function, class, or
#  module the cursor is inside."
# =====================================================================

def test_inside_a_function(tmp_path):
    got = ctx(tmp_path, "def f():\n    val<|> = 1\n")
    assert got == [{"name": "f", "type": "function", "line": 1, "column": 0}]


def test_inside_a_class_body(tmp_path):
    got = ctx(tmp_path, "class C:\n    attr<|> = 1\n")
    assert got == [{"name": "C", "type": "class", "line": 1, "column": 0}]


# "| `type` | string | `"class"` or `"function"`. |"
def test_a_method_is_a_function(tmp_path):
    got = ctx(tmp_path, "class C:\n    def m(self):\n        pa<|>ss\n")
    assert [c["type"] for c in got] == ["class", "function"]


def test_an_async_function_is_a_function(tmp_path):
    got = ctx(tmp_path, "async def f():\n    val<|> = 1\n")
    assert [c["type"] for c in got] == ["function"]


# =====================================================================
# "The `context` array is ordered from outermost to innermost scope. The first
#  element is the outermost non-module scope."
# =====================================================================

def test_class_then_method_order(tmp_path):
    got = ctx(tmp_path, "class C:\n    def m(self):\n        pa<|>ss\n")
    assert [c["name"] for c in got] == ["C", "m"]


def test_nested_functions_order(tmp_path):
    got = ctx(tmp_path, "def outer():\n    def inner():\n        pa<|>ss\n")
    assert [c["name"] for c in got] == ["outer", "inner"]


def test_three_levels_deep(tmp_path):
    src = ("class A:\n"
           "    class B:\n"
           "        def m(self):\n"
           "            pa<|>ss\n")
    got = ctx(tmp_path, src)
    assert [(c["name"], c["type"]) for c in got] == [
        ("A", "class"), ("B", "class"), ("m", "function")]


def test_module_scope_is_never_an_element(tmp_path):
    got = ctx(tmp_path, "def f():\n    pa<|>ss\n")
    assert all(c["type"] != "module" for c in got)
    assert len(got) == 1


# =====================================================================
# "| `line` | int | 1-based line of the scope's definition. |"
# "| `column` | int | 0-based column. |"
# =====================================================================

def test_line_is_the_definition_line(tmp_path):
    src = "x = 1\n\n\ndef f():\n    pa<|>ss\n"
    assert ctx(tmp_path, src)[0]["line"] == 4


def test_column_is_zero_based_for_a_top_level_def(tmp_path):
    assert ctx(tmp_path, "def f():\n    pa<|>ss\n")[0]["column"] == 0


def test_column_of_an_indented_method(tmp_path):
    got = ctx(tmp_path, "class C:\n    def m(self):\n        pa<|>ss\n")
    assert got[1]["column"] == 4
    assert got[1]["line"] == 2


def test_entries_carry_exactly_the_documented_fields(tmp_path):
    for entry in ctx(tmp_path, "class C:\n    def m(self):\n        pa<|>ss\n"):
        assert set(entry) == {"name", "type", "line", "column"}


# "| `name` | string | Name of the scope (class name, function name). |"
def test_name_is_the_scope_name(tmp_path):
    got = ctx(tmp_path, "def compute_total():\n    pa<|>ss\n")
    assert got[0]["name"] == "compute_total"


# =====================================================================
# Edge cases (T112)
# =====================================================================

def test_decorated_function_reports_the_def_line(tmp_path):
    src = "import functools\n\n@functools.cache\ndef f():\n    pa<|>ss\n"
    assert ctx(tmp_path, src)[0]["line"] == 4


def test_cursor_in_a_parameter_default_is_inside_the_function(tmp_path):
    got = ctx(tmp_path, "def f(a=<|>1):\n    pass\n")
    assert [c["name"] for c in got] == ["f"]


def test_cursor_on_the_def_line_is_inside_the_function(tmp_path):
    got = ctx(tmp_path, "def f<|>():\n    pass\n")
    assert [c["name"] for c in got] == ["f"]


def test_lambdas_do_not_appear(tmp_path):
    got = ctx(tmp_path, "def f():\n    g = lambda z: z<|>\n")
    assert [c["name"] for c in got] == ["f"]


def test_comprehensions_do_not_appear(tmp_path):
    got = ctx(tmp_path, "def f():\n    return [i<|> for i in range(3)]\n")
    assert [c["name"] for c in got] == ["f"]


def test_a_file_with_a_syntax_error_does_not_crash(tmp_path):
    r = context_raw(tmp_path, {"main.py": "def f():\n    x = = 1<|>\n"})
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert isinstance(json.loads(r.stdout)["context"], list)


def test_context_accepts_the_setting_flag(tmp_path):
    r = context_raw(tmp_path, {"main.py": "def f():\n    pa<|>ss\n"},
                    extra=["--setting", "add_bracket=true"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
