"""Spec section: the `extract-variable` subcommand."""
import json

import pytest

from conftest import (CURSOR, extract_var_raw, extract_var_in, only_file,
                      run_raw)

C = CURSOR


# --- Phrase: "python sith.py extract-variable <file> <line> <col> --until
#     <line>:<col> --name <name>" — the command exists and exits 0.
def test_extract_variable_command_exists(tmp_path):
    files = {"example.py": "value = " + C + "1 + 2\n"}
    proc = extract_var_raw(tmp_path, files, "1:13", "total")
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout)


# --- Phrase: "Extract the expression from `<line>:<col>` to `--until
#     <line>:<col>` into a new variable."
def test_expression_is_extracted(tmp_path):
    files = {"example.py": "value = " + C + "1 + 2\n"}
    data = extract_var_in(tmp_path, files, "1:13", "total")
    assert only_file(data) == "total = 1 + 2\nvalue = total\n"


# --- Phrase: "The new assignment is inserted on the line immediately before
#     the statement containing the expression, ..."
def test_assignment_goes_on_the_previous_line(tmp_path):
    code = "a = 0\nvalue = " + C + "1 + 2\nb = 3\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "2:13", "total")
    assert only_file(data) == "a = 0\ntotal = 1 + 2\nvalue = total\nb = 3\n"


# --- Phrase: "... at the same indentation level."
def test_assignment_keeps_the_indentation(tmp_path):
    code = "def f():\n    value = " + C + "1 + 2\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "2:17", "total")
    assert only_file(data) == (
        "def f():\n"
        "    total = 1 + 2\n"
        "    value = total\n"
    )


# --- Phrase: "The original expression is replaced with the variable name."
def test_only_the_selection_is_replaced(tmp_path):
    code = "value = " + C + "foo(1) + 2\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "1:14", "call")
    assert only_file(data) == "call = foo(1)\nvalue = call + 2\n"


# --- Phrase: the statement containing the expression may be a block header.
def test_extract_out_of_a_block_header(tmp_path):
    code = "if " + C + "foo(1):\n    pass\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "1:9", "flag")
    assert only_file(data) == "flag = foo(1)\nif flag:\n    pass\n"


# --- Phrase: the selection may span lines inside a multi-line statement.
def test_extract_from_a_multiline_statement(tmp_path):
    code = "value = (\n    " + C + "1 + 2\n)\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "2:9", "total")
    assert only_file(data) == "total = 1 + 2\nvalue = (\n    total\n)\n"


# --- Phrase: "If the selection cuts across an expression boundary (e.g.,
#     selects half a function call), exit 1 with "selection is not a complete
#     expression"."
def test_partial_call_exits_1(tmp_path):
    code = "value = " + C + "foo(1) + 2\n"
    proc = extract_var_raw(tmp_path, {"example.py": code}, "1:13", "call")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "selection is not a complete expression" in proc.stderr


def test_selection_crossing_operators_exits_1(tmp_path):
    code = "value = " + C + "1 + 2 + 3\n"
    proc = extract_var_raw(tmp_path, {"example.py": code}, "1:15", "total")
    assert proc.returncode == 1
    assert "selection is not a complete expression" in proc.stderr


def test_selection_of_whitespace_exits_1(tmp_path):
    code = "value = 1 " + C + "+ 2\n"
    proc = extract_var_raw(tmp_path, {"example.py": code}, "1:12", "total")
    assert proc.returncode == 1


# --- Phrase: "`--name` must be a valid Python identifier. Exit 1 if not."
@pytest.mark.parametrize("bad", ["2bad", "with space", "", "a-b"])
def test_invalid_name_exits_1(tmp_path, bad):
    files = {"example.py": "value = " + C + "1 + 2\n"}
    proc = extract_var_raw(tmp_path, files, "1:13", bad)
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "Output format: Same as `rename`."
def test_payload_shape(tmp_path):
    files = {"example.py": "value = " + C + "1 + 2\n"}
    data = extract_var_in(tmp_path, files, "1:13", "total")
    assert "changed_files" in data
    assert data.get("renames", {}) == {}


def test_diff_output(tmp_path):
    files = {"example.py": "value = " + C + "1 + 2\n"}
    proc = extract_var_raw(tmp_path, files, "1:13", "total", diff=True)
    assert proc.returncode == 0, proc.stderr
    assert "+total = 1 + 2" in proc.stdout
    assert "+value = total" in proc.stdout


# --- Phrase: a whole sub-expression, not just a literal, can be selected.
def test_extract_a_nested_call(tmp_path):
    code = "value = outer(" + C + "inner(1))\n"
    data = extract_var_in(tmp_path, {"example.py": code}, "1:22", "part")
    assert only_file(data) == "part = inner(1)\nvalue = outer(part)\n"


# --- Phrase: a missing file is a tool-level failure.
def test_missing_file_exits_1(tmp_path):
    proc = run_raw("extract-variable", str(tmp_path / "nope.py"), 1, 0,
                   "--until", "1:1", "--name", "x", cwd=str(tmp_path))
    assert proc.returncode == 1
