"""Spec section: the `extract-function` subcommand."""
import json

import pytest

from conftest import (CURSOR, extract_fn_raw, extract_fn_in, only_file,
                      run_raw)

C = CURSOR


# --- Phrase: "python sith.py extract-function <file> <line> <col> --until
#     <line>:<col> --name <name>" — the command exists and exits 0.
def test_extract_function_command_exists(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    proc = extract_fn_raw(tmp_path, {"example.py": code}, "3:13", "compute")
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout)


# --- Phrase: "Extract the code from `<line>:<col>` to `--until <line>:<col>`
#     into a new function." and "The new function is inserted immediately
#     before the function/class containing the selection, at the same
#     indentation level as the enclosing function."
def test_function_is_inserted_before_the_enclosing_function(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    data = extract_fn_in(tmp_path, {"example.py": code}, "3:13", "compute")
    assert only_file(data) == (
        "def compute(a):\n"
        "    b = a + 1\n"
        "    return b\n"
        "\n"
        "def outer():\n"
        "    a = 1\n"
        "    b = compute(a)\n"
        "    return b\n"
    )


# --- Phrase: "Parameter detection: Variables read in the selected statements
#     but defined outside the selection become function parameters, ordered by
#     first appearance in the selected code."
def test_parameters_follow_first_appearance(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    b = 2\n"
        "    " + C + "c = b + a\n"
        "    return c\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "4:13", "mix"))
    assert out.startswith("def mix(b, a):\n")


def test_names_bound_inside_the_selection_are_not_parameters(tmp_path):
    code = (
        "def outer():\n"
        "    " + C + "a = 1\n"
        "    b = a + 1\n"
        "    return b\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "3:13", "make"))
    assert out.startswith("def make():\n")


# --- Phrase (T97): imported names and module-level functions are not
#     variables, so they do not become parameters.
def test_imports_are_not_parameters(tmp_path):
    code = (
        "import math\n"
        "\n"
        "\n"
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = math.sqrt(a)\n"
        "    return b\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "6:20",
                                  "root"))
    assert "def root(a):\n" in out


def test_module_functions_are_not_parameters(tmp_path):
    code = (
        "def helper(v):\n"
        "    return v\n"
        "\n"
        "\n"
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = helper(a)\n"
        "    return b\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "7:17", "use"))
    assert "def use(a):\n" in out


# --- Phrase: "Return value detection: Variables assigned in the selected
#     statements and used after the selection become return values. If one
#     variable: `return var`."
def test_single_return_value(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "3:13",
                                  "compute"))
    assert "    return b\n" in out
    assert "    b = compute(a)\n" in out


# --- Phrase: "If multiple: return a tuple in source order and update the call
#     site to tuple-unpack in the same order."
def test_multiple_return_values(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    c = a + 2\n"
        "    return b + c\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "4:13",
                                  "split"))
    assert out == (
        "def split(a):\n"
        "    b = a + 1\n"
        "    c = a + 2\n"
        "    return b, c\n"
        "\n"
        "def outer():\n"
        "    a = 1\n"
        "    b, c = split(a)\n"
        "    return b + c\n"
    )


# --- Phrase: a variable assigned in the selection but never read afterwards is
#     not returned.
def test_no_return_value(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "print(a)\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "3:12",
                                  "show"))
    assert out == (
        "def show(a):\n"
        "    print(a)\n"
        "\n"
        "def outer():\n"
        "    a = 1\n"
        "    show(a)\n"
    )


# --- Phrase: "The selection must span one or more complete statements (full
#     lines)."
def test_multiple_statements_are_extracted(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    c = b + 1\n"
        "    return c\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "4:13",
                                  "chain"))
    assert "    b = a + 1\n    c = b + 1\n" in out


# --- Phrase: "If it spans a partial statement, exit 1."
def test_partial_start_exits_1(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    b = " + C + "a + 1\n"
        "    return b\n"
    )
    proc = extract_fn_raw(tmp_path, {"example.py": code}, "3:13", "compute")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_partial_end_exits_1(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    proc = extract_fn_raw(tmp_path, {"example.py": code}, "3:9", "compute")
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "If the selection is at module level (not inside a function), the
#     new function is inserted immediately before the first selected line."
def test_module_level_extraction(tmp_path):
    code = (
        "x = 1\n"
        + C + "y = x + 1\n"
        "print(y)\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "2:9", "bump"))
    assert out == (
        "x = 1\n"
        "def bump(x):\n"
        "    y = x + 1\n"
        "    return y\n"
        "\n"
        "y = bump(x)\n"
        "print(y)\n"
    )


# --- Phrase: "The parameter-detection rule still applies at module level: if
#     the selected statements read a module-level name defined outside the
#     selection, that name becomes a parameter to the extracted function rather
#     than staying an implicit global in the extracted body."
def test_module_level_name_becomes_a_parameter(tmp_path):
    code = (
        "base = 10\n"
        + C + "total = base * 2\n"
        "print(total)\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "2:16",
                                  "scale"))
    assert "def scale(base):\n" in out
    assert "total = scale(base)\n" in out


# --- Phrase: "at the same indentation level as the enclosing function" — a
#     method's helper lands in the class body.
def test_extraction_out_of_a_method(tmp_path):
    code = (
        "class Thing:\n"
        "    def run(self):\n"
        "        a = 1\n"
        "        " + C + "b = a + 1\n"
        "        return b\n"
    )
    out = only_file(extract_fn_in(tmp_path, {"example.py": code}, "4:17",
                                  "step"))
    assert out == (
        "class Thing:\n"
        "    def step(a):\n"
        "        b = a + 1\n"
        "        return b\n"
        "\n"
        "    def run(self):\n"
        "        a = 1\n"
        "        b = step(a)\n"
        "        return b\n"
    )


# --- Phrase: "`--name` must be a valid Python identifier. Exit 1 if not."
@pytest.mark.parametrize("bad", ["2bad", "with space", "", "a-b"])
def test_invalid_name_exits_1(tmp_path, bad):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    proc = extract_fn_raw(tmp_path, {"example.py": code}, "3:13", bad)
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "Output format: Same as `rename`."
def test_payload_shape(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    data = extract_fn_in(tmp_path, {"example.py": code}, "3:13", "compute")
    assert "changed_files" in data
    assert data.get("renames", {}) == {}


def test_diff_output(tmp_path):
    code = (
        "def outer():\n"
        "    a = 1\n"
        "    " + C + "b = a + 1\n"
        "    return b\n"
    )
    proc = extract_fn_raw(tmp_path, {"example.py": code}, "3:13", "compute",
                          diff=True)
    assert proc.returncode == 0, proc.stderr
    assert "+def compute(a):" in proc.stdout
    assert "+    b = compute(a)" in proc.stdout


# --- Phrase: a missing file is a tool-level failure.
def test_missing_file_exits_1(tmp_path):
    proc = run_raw("extract-function", str(tmp_path / "nope.py"), 1, 0,
                   "--until", "1:1", "--name", "x", cwd=str(tmp_path))
    assert proc.returncode == 1
