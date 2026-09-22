"""Spec: New Subcommand: `context`."""

import json

from conftest import invoke, write_source


def context(tmp_path, source, **options):
    """Ask for the scope context at a ``$``-marked cursor."""
    path, line, col = write_source(tmp_path, source, **options)
    return invoke("context", path, line, col)


def scopes(tmp_path, source, **options):
    return context(tmp_path, source, **options).data["context"]


# Spec: "python sith.py context <file> <line> <col> [--project <dir>]"
def test_context_subcommand_is_accepted(tmp_path):
    result = context(tmp_path, "value = 1$\n")
    assert result.code == 0
    assert list(json.loads(result.stdout)) == ["context"]


def test_context_accepts_the_project_flag(tmp_path):
    path, line, col = write_source(tmp_path, "value = 1$\n")
    assert invoke("context", path, line, col, project=tmp_path).code == 0


# Spec: "If the cursor is at module level, the array is empty."
def test_module_level_has_no_context(tmp_path):
    assert scopes(tmp_path, "value = 1$\n") == []


# Spec: "Return the scope context at the cursor position - what function,
# class, or module the cursor is inside."
def test_a_cursor_inside_a_function(tmp_path):
    assert scopes(tmp_path, "def run():\n    valu$e = 1\n") == [
        {"name": "run", "type": "function", "line": 1, "column": 4}
    ]


# Spec: "`type` | string | `"class"` or `"function"`."
def test_a_cursor_inside_a_class_body(tmp_path):
    assert scopes(tmp_path, "class Widget:\n    size$ = 1\n") == [
        {"name": "Widget", "type": "class", "line": 1, "column": 6}
    ]


# Spec: "The `context` array is ordered from outermost to innermost scope. The
# first element is the outermost non-module scope."
def test_a_method_reports_its_class_first(tmp_path):
    source = "class Widget:\n    def draw(self):\n        pa$ss\n"
    assert [item["name"] for item in scopes(tmp_path, source)] == ["Widget", "draw"]


def test_nested_functions_are_ordered_outermost_first(tmp_path):
    source = "def outer():\n    def inner():\n        val$ue = 1\n"
    assert [item["name"] for item in scopes(tmp_path, source)] == ["outer", "inner"]


# Spec: "`line` | int | 1-based line of the scope's definition."
# "`column` | int | 0-based column."
def test_positions_point_at_the_scope_definition(tmp_path):
    source = "class Widget:\n    def draw(self):\n        pa$ss\n"
    assert scopes(tmp_path, source) == [
        {"name": "Widget", "type": "class", "line": 1, "column": 6},
        {"name": "draw", "type": "function", "line": 2, "column": 8},
    ]


# Spec: "what function, class, or module the cursor is inside" - the signature
# line of a definition is inside the scope it opens.
def test_a_cursor_on_a_nested_definition_line(tmp_path):
    source = "class Widget:\n    def dr$aw(self):\n        pass\n"
    assert [item["name"] for item in scopes(tmp_path, source)] == ["Widget"]


# Spec: the cursor position is read the way every other command reads it.
def test_a_position_out_of_range_exits_one(tmp_path):
    path, _, _ = write_source(tmp_path, "value = 1$\n")
    result = invoke("context", path, 99, 0)
    assert result.code == 1
    assert result.stderr.strip()


# Spec: "Output is JSON to STDOUT" - `context` keeps the shared format.
def test_output_is_compact_and_newline_terminated(tmp_path):
    result = context(tmp_path, "def run():\n    valu$e = 1\n")
    assert result.stdout.endswith("\n")
    assert result.stdout.rstrip("\n") == json.dumps(
        json.loads(result.stdout), separators=(",", ":")
    )
