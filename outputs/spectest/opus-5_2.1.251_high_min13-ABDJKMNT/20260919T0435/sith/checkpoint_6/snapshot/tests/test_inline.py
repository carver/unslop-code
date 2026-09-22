"""The `inline` command: replacing a variable with its value."""

from conftest import run_cli


# "python sith.py inline <file> <line> <col> [--diff] [--project <dir>]"
def test_inline_accepts_file_line_col(inline):
    assert inline("x| = 1\nprint(x)\n").returncode == 0


# "replace all references with the variable's value and delete the definition"
def test_reference_is_replaced_by_the_value(inline):
    changed = inline("x| = 1\nprint(x)\n").changed_files
    assert changed["sample.py"] == "print(1)\n"


def test_every_reference_is_replaced(inline):
    changed = inline("x| = 1\nprint(x)\nprint(x + 2)\n").changed_files
    assert changed["sample.py"] == "print(1)\nprint(1 + 2)\n"


def test_inline_from_a_reference_finds_the_definition(inline):
    changed = inline("x = 1\nprint(x|)\n").changed_files
    assert changed["sample.py"] == "print(1)\n"


def test_the_definition_line_is_deleted(inline):
    changed = inline("a = 0\nx| = 1\nb = 2\nprint(x)\n").changed_files
    assert changed["sample.py"] == "a = 0\nb = 2\nprint(1)\n"


def test_a_call_expression_is_inlined(inline):
    changed = inline("x| = compute(1)\nprint(x)\n").changed_files
    assert changed["sample.py"] == "print(compute(1))\n"


def test_a_local_variable_is_inlined_inside_its_function(inline):
    source = "def f(n):\n    do|uble = n * 2\n    return double + 1\n"
    changed = inline(source).changed_files
    assert changed["sample.py"] == "def f(n):\n    return n * 2 + 1\n"


# "Wrap the inlined expression in parentheses when needed to preserve evaluation order"
def test_a_sum_inlined_into_a_product_is_bracketed(inline):
    changed = inline("x| = a + b\ny = x * 2\n").changed_files
    assert changed["sample.py"] == "y = (a + b) * 2\n"


def test_a_sum_inlined_into_a_sum_is_not_bracketed(inline):
    changed = inline("x| = a + b\ny = x + 2\n").changed_files
    assert changed["sample.py"] == "y = a + b + 2\n"


def test_the_right_hand_side_of_a_subtraction_is_bracketed(inline):
    changed = inline("x| = a + b\ny = 2 - x\n").changed_files
    assert changed["sample.py"] == "y = 2 - (a + b)\n"


def test_a_call_argument_is_not_bracketed(inline):
    changed = inline("x| = a + b\ny = f(x)\n").changed_files
    assert changed["sample.py"] == "y = f(a + b)\n"


def test_a_negated_expression_is_bracketed(inline):
    changed = inline("x| = a + b\ny = -x\n").changed_files
    assert changed["sample.py"] == "y = -(a + b)\n"


def test_an_attribute_owner_is_bracketed(inline):
    changed = inline("x| = a + b\ny = x.real\n").changed_files
    assert changed["sample.py"] == "y = (a + b).real\n"


def test_an_or_inside_an_and_is_bracketed(inline):
    changed = inline("x| = a or b\ny = x and c\n").changed_files
    assert changed["sample.py"] == "y = (a or b) and c\n"


def test_an_atom_is_never_bracketed(inline):
    changed = inline("x| = value\ny = x * 2\n").changed_files
    assert changed["sample.py"] == "y = value * 2\n"


def test_a_bare_tuple_is_bracketed(inline):
    changed = inline("x| = 1, 2\nprint(x)\n").changed_files
    assert changed["sample.py"] == "print((1, 2))\n"


def test_an_already_bracketed_value_is_not_bracketed_twice(inline):
    changed = inline("x| = (a + b)\ny = x * 2\n").changed_files
    assert changed["sample.py"] == "y = (a + b) * 2\n"


# "Cannot inline function or class definitions - exit 1 with
#  \"cannot inline a function/class definition\"."
def test_inlining_a_function_is_rejected(inline):
    result = inline("def he|lper():\n    pass\n\n\nhelper()\n", expect_ok=False)
    assert result.returncode == 1
    assert "cannot inline a function/class definition" in result.stderr


def test_inlining_a_class_is_rejected(inline):
    result = inline("class Th|ing:\n    pass\n\n\nThing()\n", expect_ok=False)
    assert result.returncode == 1
    assert "cannot inline a function/class definition" in result.stderr


def test_inlining_a_function_emits_no_edits(inline):
    assert inline("def he|lper():\n    pass\n\n\nhelper()\n", expect_ok=False).stdout == ""


# "The name must have at least one reference beyond the definition. If the name
#  is unused, exit 1 with \"name has no references to inline\"."
def test_an_unused_variable_is_rejected(inline):
    result = inline("x| = 1\ny = 2\n", expect_ok=False)
    assert result.returncode == 1
    assert "name has no references to inline" in result.stderr


def test_an_unused_variable_emits_no_edits(inline):
    assert inline("x| = 1\ny = 2\n", expect_ok=False).stdout == ""


# "The name must be a simple assignment (`x = <expr>`)."
def test_a_tuple_target_cannot_be_inlined(inline):
    result = inline("x|, y = 1, 2\nprint(x)\n", expect_ok=False)
    assert result.returncode == 1


def test_a_parameter_cannot_be_inlined(inline):
    result = inline("def f(n|):\n    return n\n", expect_ok=False)
    assert result.returncode == 1


def test_a_loop_target_cannot_be_inlined(inline):
    result = inline("for it|em in [1]:\n    print(item)\n", expect_ok=False)
    assert result.returncode == 1


# "If the cursor is not on a name, exit 1."
def test_cursor_not_on_a_name_is_rejected(inline):
    assert inline("x = 1\nprint(x)\n   |\n", expect_ok=False).returncode == 1


# "**Output format:** Same as `rename` - `changed_files` (JSON) or unified diff"
def test_payload_has_changed_files_and_renames(inline):
    payload = inline("x| = 1\nprint(x)\n").payload
    assert set(payload) == {"changed_files", "renames"}


def test_inline_reports_no_path_renames(inline):
    assert inline("x| = 1\nprint(x)\n").renames == {}


def test_only_changed_files_are_reported(inline):
    changed = inline("x| = 1\nprint(x)\n", files={"other.py": "y = 2\n"}).changed_files
    assert list(changed) == ["sample.py"]


# "unified diff (`--diff`)"
def test_diff_output_is_plain_text(inline):
    stdout = inline("x| = 1\nprint(x)\n", diff=True).stdout
    assert not stdout.startswith("{")
    assert "-x = 1" in stdout
    assert "+print(1)" in stdout


# "On error, print a message to STDERR and exit 1."
def test_inline_on_a_missing_file_fails(workdir):
    result = run_cli("inline", str(workdir / "missing.py"), 1, 0)
    assert result.returncode == 1
    assert result.stdout == ""


# "Wrap the inlined expression in parentheses when needed" - brackets spanning
# lines are what holds the expression together at all.
def test_a_value_written_across_lines_keeps_its_brackets(inline):
    source = "def f(a, b):\n    tot|al = (a +\n             b)\n    return total\n"
    changed = inline(source).changed_files
    assert changed["sample.py"] == "def f(a, b):\n    return (a +\n             b)\n"
