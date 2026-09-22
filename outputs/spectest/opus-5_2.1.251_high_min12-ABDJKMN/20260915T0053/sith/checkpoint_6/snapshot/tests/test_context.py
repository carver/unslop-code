"""Spec section: New Subcommand `context`."""
import json

from conftest import (context_at, context_raw, run_raw, split_cursor,
                      write_source)


# --- Phrase: "python sith.py context <file> <line> <col>" — a `context` array.
def test_context_payload_shape(tmp_path):
    proc = context_raw(tmp_path, "def f():\n    x█ = 1\n")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"context"}
    assert isinstance(data["context"], list)


# --- Phrase: "If the cursor is at module level, the array is empty."
def test_module_level_context_is_empty(tmp_path):
    assert context_at(tmp_path, "x = █1\n") == []


def test_module_level_between_definitions(tmp_path):
    code = "def f():\n    pass\n\n\nva█lue = 1\n"
    assert context_at(tmp_path, code) == []


# --- Phrase: "what function, class, or module the cursor is inside" — a plain
#     function body.
def test_inside_a_function(tmp_path):
    rows = context_at(tmp_path, "def outer():\n    y█ = 1\n")
    assert [(r["name"], r["type"]) for r in rows] == [("outer", "function")]


# --- Phrase: a class body.
def test_inside_a_class(tmp_path):
    rows = context_at(tmp_path, "class Alpha:\n    at█tr = 1\n")
    assert [(r["name"], r["type"]) for r in rows] == [("Alpha", "class")]


# --- Phrase: "The `context` array is ordered from outermost to innermost
#     scope. The first element is the outermost non-module scope."
def test_ordering_outermost_first(tmp_path):
    code = (
        "class Alpha:\n"
        "    def method(self):\n"
        "        def inner():\n"
        "            va█lue = 1\n"
        "        return inner\n"
    )
    rows = context_at(tmp_path, code)
    assert [(r["name"], r["type"]) for r in rows] == [
        ("Alpha", "class"), ("method", "function"), ("inner", "function")]


# --- Phrase: a method inside a class inside a function.
def test_mixed_nesting(tmp_path):
    code = (
        "def factory():\n"
        "    class Inner:\n"
        "        def run(self):\n"
        "            pa█ss\n"
        "    return Inner\n"
    )
    rows = context_at(tmp_path, code)
    assert [(r["name"], r["type"]) for r in rows] == [
        ("factory", "function"), ("Inner", "class"), ("run", "function")]


# --- Phrase: `name` — "Name of the scope (class name, function name)."
#     `type` — "class" or "function".
def test_row_fields(tmp_path):
    rows = context_at(tmp_path, "class Alpha:\n    def m(self):\n        p█ = 1\n")
    for row in rows:
        assert set(row) == {"name", "type", "line", "column"}
        assert row["type"] in ("class", "function")
        assert isinstance(row["line"], int)
        assert isinstance(row["column"], int)


# --- Phrase: `line` — "1-based line of the scope's definition."
def test_line_is_the_definition_line(tmp_path):
    code = (
        "\n"
        "\n"
        "class Alpha:\n"
        "\n"
        "    def method(self):\n"
        "        x█ = 1\n"
    )
    rows = context_at(tmp_path, code)
    assert [r["line"] for r in rows] == [3, 5]


# --- Phrase: `column` — "0-based column."
def test_column_is_zero_based(tmp_path):
    code = "class Alpha:\n    def method(self):\n        x█ = 1\n"
    rows = context_at(tmp_path, code)
    assert rows[0]["column"] == len("class ")
    assert rows[1]["column"] == len("    def ")


# --- Phrase: async functions are functions.
def test_async_function_is_a_function(tmp_path):
    rows = context_at(tmp_path, "async def go():\n    aw█ait x\n")
    assert [(r["name"], r["type"]) for r in rows] == [("go", "function")]


# --- Phrase: a decorated definition reports the `def` line, not the decorator.
def test_decorated_definition(tmp_path):
    code = "@deco\ndef wrapped():\n    val█ue = 1\n"
    rows = context_at(tmp_path, code)
    assert [(r["name"], r["line"]) for r in rows] == [("wrapped", 2)]


# --- Phrase: "[--project <dir>]" is accepted.
def test_project_flag_is_accepted(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    src, line, col = split_cursor("def f():\n    x█ = 1\n")
    path = write_source(proj, src, "main.py")
    proc = run_raw("context", str(path), line, col, "--project", str(proj),
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["context"][0]["name"] == "f"


# --- Phrase: `context` reports file and position errors like the other cursor
#     commands.
def test_missing_file(tmp_path):
    proc = run_raw("context", str(tmp_path / "gone.py"), 1, 0,
                   cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_out_of_range_line(tmp_path):
    path = write_source(tmp_path, "x = 1\n")
    proc = run_raw("context", str(path), 99, 0, cwd=str(tmp_path))
    assert proc.returncode == 1


def test_requires_three_arguments(tmp_path):
    path = write_source(tmp_path, "x = 1\n")
    proc = run_raw("context", str(path), 1, cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: output framing — one compact, newline-terminated JSON object.
def test_output_framing(tmp_path):
    proc = context_raw(tmp_path, "def f():\n    x█ = 1\n")
    assert proc.stdout.endswith("\n")
    assert proc.stdout.count("\n") == 1
    assert ", " not in proc.stdout


# --- Phrase: a syntactically broken file is repaired rather than rejected.
def test_broken_file_is_tolerated(tmp_path):
    code = "def f():\n    x = (\n    y█ = 1\n"
    proc = context_raw(tmp_path, code)
    assert proc.returncode == 0, proc.stderr
