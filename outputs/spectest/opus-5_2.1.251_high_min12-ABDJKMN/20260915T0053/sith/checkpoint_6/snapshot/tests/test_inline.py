"""Spec section: the `inline` subcommand."""
import json

from conftest import CURSOR, inline_raw, inline_in, only_file, run_raw

C = CURSOR


# --- Phrase: "python sith.py inline <file> <line> <col> [--diff]
#     [--project <dir>]" — the command exists and exits 0.
def test_inline_command_exists(tmp_path):
    files = {"example.py": "x" + C + " = 1\nprint(x)\n"}
    proc = inline_raw(tmp_path, files)
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout)


# --- Phrase: "Inline a variable — replace all references with the variable's
#     value ..."
def test_reference_is_replaced_by_the_value(tmp_path):
    files = {"example.py": "x" + C + " = 1\nprint(x)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(1)\n"


def test_every_reference_is_replaced(tmp_path):
    files = {"example.py": "n" + C + " = 5\nprint(n)\nprint(n + 1)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(5)\nprint(5 + 1)\n"


# --- Phrase: "... and delete the definition."
def test_definition_line_is_deleted(tmp_path):
    files = {"example.py": "x" + C + " = 1\nprint(x)\n"}
    assert "x = 1" not in only_file(inline_in(tmp_path, files))


# --- Phrase: "The name must be a simple assignment (`x = <expr>`)." — a call
#     expression inlines as written.
def test_inline_a_call_expression(tmp_path):
    files = {"example.py": "na" + C + "me = compute()\nprint(name)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(compute())\n"


# --- Phrase: "Cannot inline function or class definitions — exit 1 with
#     "cannot inline a function/class definition"."
def test_inline_function_definition_exits_1(tmp_path):
    code = "def hel" + C + "per():\n    return 1\n\n\nhelper()\n"
    proc = inline_raw(tmp_path, {"example.py": code})
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "cannot inline a function/class definition" in proc.stderr


def test_inline_class_definition_exits_1(tmp_path):
    code = "class Thi" + C + "ng:\n    pass\n\n\nThing()\n"
    proc = inline_raw(tmp_path, {"example.py": code})
    assert proc.returncode == 1
    assert "cannot inline a function/class definition" in proc.stderr


# --- Phrase: "The name must have at least one reference beyond the definition.
#     If the name is unused, exit 1 with "name has no references to inline"."
def test_unused_name_exits_1(tmp_path):
    files = {"example.py": "unu" + C + "sed = 1\nprint(2)\n"}
    proc = inline_raw(tmp_path, files)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "name has no references to inline" in proc.stderr


# --- Phrase: "Wrap the inlined expression in parentheses when needed to
#     preserve evaluation order".
def test_parens_added_for_lower_precedence(tmp_path):
    files = {"example.py": "tot" + C + "al = a + b\nresult = total * 2\n"}
    assert only_file(inline_in(tmp_path, files)) == "result = (a + b) * 2\n"


def test_parens_not_added_when_unnecessary(tmp_path):
    files = {"example.py": "tot" + C + "al = a * b\nresult = total + 2\n"}
    assert only_file(inline_in(tmp_path, files)) == "result = a * b + 2\n"


def test_parens_for_a_call_argument_are_not_added(tmp_path):
    files = {"example.py": "tot" + C + "al = a + b\nprint(total)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(a + b)\n"


def test_parens_around_a_tuple_in_a_call(tmp_path):
    files = {"example.py": "pai" + C + "r = 1, 2\nprint(pair)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print((1, 2))\n"


def test_parens_for_unary_minus(tmp_path):
    files = {"example.py": "tot" + C + "al = a + b\nresult = -total\n"}
    assert only_file(inline_in(tmp_path, files)) == "result = -(a + b)\n"


def test_parens_for_attribute_access(tmp_path):
    files = {"example.py": "tot" + C + "al = a + b\nprint(total.real)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print((a + b).real)\n"


def test_parens_for_a_conditional_value(tmp_path):
    files = {"example.py": "pic" + C + "k = a if c else b\nprint(pick + 1)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print((a if c else b) + 1)\n"


def test_right_operand_of_subtraction_is_parenthesised(tmp_path):
    files = {"example.py": "de" + C + "lta = a - b\nprint(1 - delta)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(1 - (a - b))\n"


# --- Phrase: "Output format: Same as `rename` — `changed_files` (JSON) ..."
def test_inline_payload_shape(tmp_path):
    files = {"example.py": "x" + C + " = 1\nprint(x)\n"}
    data = inline_in(tmp_path, files)
    assert "changed_files" in data
    assert data.get("renames", {}) == {}


# --- Phrase: "... or unified diff (`--diff`)."
def test_inline_diff_is_plain_text(tmp_path):
    files = {"example.py": "x" + C + " = 1\nprint(x)\n"}
    proc = inline_raw(tmp_path, files, diff=True)
    assert proc.returncode == 0, proc.stderr
    assert "-x = 1" in proc.stdout
    assert "+print(1)" in proc.stdout


# --- Phrase: inlining a local variable inside a function body.
def test_inline_inside_a_function(tmp_path):
    code = (
        "def outer():\n"
        "    ste" + C + "p = 2\n"
        "    return step * 3\n"
    )
    out = only_file(inline_in(tmp_path, {"example.py": code}))
    assert out == "def outer():\n    return 2 * 3\n"


# --- Phrase: a missing file is a tool-level failure.
def test_missing_file_exits_1(tmp_path):
    proc = run_raw("inline", str(tmp_path / "nope.py"), 1, 0, cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase (T107): "delete the definition" when the assignment shares its
#     line with other code.
def test_semicolon_separated_definition(tmp_path):
    files = {"example.py": "x" + C + " = 1; print(x)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print(1)\n"


def test_compound_header_body_gets_pass(tmp_path):
    files = {"example.py": "if c: x" + C + " = 1\nprint(x)\n"}
    assert only_file(inline_in(tmp_path, files)) == "if c: pass\nprint(1)\n"


# --- Phrase: "Cannot inline function or class definitions" — an imported name
#     is not a simple assignment either, and still exits 1.
def test_inline_an_import_exits_1(tmp_path):
    files = {"example.py": "import o" + C + "s\nprint(os)\n"}
    proc = inline_raw(tmp_path, files)
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_inline_a_parameter_exits_1(tmp_path):
    code = "def f(va" + C + "lue):\n    return value\n"
    proc = inline_raw(tmp_path, {"example.py": code})
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_inline_an_augmented_assignment_exits_1(tmp_path):
    code = "x = 1\nx" + C + " += 2\nprint(x)\n"
    proc = inline_raw(tmp_path, {"example.py": code})
    assert proc.returncode == 1


# --- Phrase: the value keeps its own parentheses where the source had them.
def test_call_value_keeps_its_own_grouping(tmp_path):
    files = {"example.py": "tot" + C + "al = (a + b)\nprint(total * 2)\n"}
    assert only_file(inline_in(tmp_path, files)) == "print((a + b) * 2)\n"
