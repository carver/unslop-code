"""The `extract-variable` command: naming a selected expression."""

from conftest import run_cli


# "python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>"
def test_extract_variable_accepts_a_selection_and_a_name(extract_variable):
    result = extract_variable("total = |price * count$ + tax\n", name="subtotal")
    assert result.returncode == 0


# "The new assignment is inserted on the line immediately before the statement
#  containing the expression" / "The original expression is replaced with the variable name."
def test_the_expression_becomes_an_assignment_above_the_statement(extract_variable):
    changed = extract_variable("total = |price * count$ + tax\n",
                               name="subtotal").changed_files
    assert changed["sample.py"] == "subtotal = price * count\ntotal = subtotal + tax\n"


def test_a_whole_call_can_be_extracted(extract_variable):
    changed = extract_variable("print(|compute(1, 2)$)\n", name="result").changed_files
    assert changed["sample.py"] == "result = compute(1, 2)\nprint(result)\n"


def test_an_argument_can_be_extracted(extract_variable):
    changed = extract_variable("print(compute(|1 + 2$))\n", name="total").changed_files
    assert changed["sample.py"] == "total = 1 + 2\nprint(compute(total))\n"


# "at the same indentation level"
def test_the_assignment_keeps_the_statements_indentation(extract_variable):
    source = "def f(a, b):\n    return |a * b$ + 1\n"
    changed = extract_variable(source, name="scaled").changed_files
    assert changed["sample.py"] == "def f(a, b):\n    scaled = a * b\n    return scaled + 1\n"


def test_a_nested_block_keeps_its_own_indentation(extract_variable):
    source = "def f(a):\n    if a:\n        print(|a + 1$)\n"
    changed = extract_variable(source, name="bumped").changed_files
    assert changed["sample.py"] == (
        "def f(a):\n    if a:\n        bumped = a + 1\n        print(bumped)\n"
    )


def test_only_the_selected_occurrence_is_replaced(extract_variable):
    changed = extract_variable("x = |a + b$\ny = a + b\n", name="total").changed_files
    assert changed["sample.py"] == "total = a + b\nx = total\ny = a + b\n"


# "The selection must span a complete expression. If the selection cuts across an
#  expression boundary (e.g., selects half a function call), exit 1 with
#  \"selection is not a complete expression\"."
def test_half_a_call_is_rejected(extract_variable):
    result = extract_variable("x = |compute(a$) + b\n", name="part", expect_ok=False)
    assert result.returncode == 1
    assert "selection is not a complete expression" in result.stderr


def test_a_selection_across_an_operator_is_rejected(extract_variable):
    result = extract_variable("x = a |+ b$ + c\n", name="part", expect_ok=False)
    assert result.returncode == 1


def test_an_incomplete_selection_emits_no_edits(extract_variable):
    result = extract_variable("x = |compute(a$) + b\n", name="part", expect_ok=False)
    assert result.stdout == ""


# "`--name` must be a valid Python identifier. Exit 1 if not."
def test_an_invalid_name_is_rejected(extract_variable):
    result = extract_variable("x = |a + b$\n", name="not a name", expect_ok=False)
    assert result.returncode == 1


def test_a_keyword_name_is_rejected(extract_variable):
    result = extract_variable("x = |a + b$\n", name="while", expect_ok=False)
    assert result.returncode == 1


# "**Output format:** Same as `rename`."
def test_payload_has_changed_files_and_renames(extract_variable):
    payload = extract_variable("x = |a + b$\n", name="total").payload
    assert set(payload) == {"changed_files", "renames"}


def test_only_the_edited_file_is_reported(extract_variable):
    result = extract_variable("x = |a + b$\n", name="total", files={"other.py": "y = 1\n"})
    assert list(result.changed_files) == ["sample.py"]


def test_diff_output_is_plain_text(extract_variable):
    stdout = extract_variable("x = |a + b$\n", name="total", diff=True).stdout
    assert not stdout.startswith("{")
    assert "+total = a + b" in stdout
    assert "+x = total" in stdout


# "On error, print a message to STDERR and exit 1."
def test_extract_variable_on_a_missing_file_fails(workdir):
    result = run_cli("extract-variable", str(workdir / "missing.py"), 1, 0,
                     "--until", "1:3", "--name", "x")
    assert result.returncode == 1
    assert result.stdout == ""


def test_until_is_required(extract_variable):
    result = extract_variable("x = a + b\n", cursor=(1, 4), name="total", expect_ok=False)
    assert result.returncode == 1


# "The selection must span a complete expression" - including one written over
# more than one line.
def test_an_expression_spanning_lines_is_extracted(extract_variable):
    source = "x = |compute(\n    1,\n    2)$\nprint(x)\n"
    changed = extract_variable(source, name="val").changed_files
    assert changed["sample.py"] == "val = compute(\n    1,\n    2)\nx = val\nprint(x)\n"
