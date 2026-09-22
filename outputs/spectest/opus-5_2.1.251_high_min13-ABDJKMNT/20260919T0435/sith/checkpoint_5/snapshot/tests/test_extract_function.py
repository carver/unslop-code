"""The `extract-function` command: moving statements into a new function."""

from conftest import run_cli


# "python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>"
def test_extract_function_accepts_a_selection_and_a_name(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    assert extract_function(source, name="show").returncode == 0


# "The new function is inserted immediately before the function/class containing
#  the selection, at the same indentation level as the enclosing function."
def test_the_function_is_inserted_before_the_enclosing_function(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"] == (
        "def show(x):\n"
        "    print(x)\n"
        "\n"
        "def main():\n"
        "    x = 1\n"
        "    show(x)\n"
    )


def test_a_method_is_extracted_at_the_methods_indentation(extract_function):
    source = "class C:\n    def run(self):\n        x = 1\n        |print(x)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"] == (
        "class C:\n"
        "    def show(x):\n"
        "        print(x)\n"
        "\n"
        "    def run(self):\n"
        "        x = 1\n"
        "        show(x)\n"
    )


# "The selection must span one or more complete statements (full lines)."
def test_several_statements_are_extracted_together(extract_function):
    source = "def main():\n    x = 1\n    |print(x)\n    print(x + 1)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"] == (
        "def show(x):\n"
        "    print(x)\n"
        "    print(x + 1)\n"
        "\n"
        "def main():\n"
        "    x = 1\n"
        "    show(x)\n"
    )


def test_a_compound_statement_is_extracted_whole(extract_function):
    source = "def main():\n    x = 1\n    |if x:\n        print(x)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"] == (
        "def show(x):\n"
        "    if x:\n"
        "        print(x)\n"
        "\n"
        "def main():\n"
        "    x = 1\n"
        "    show(x)\n"
    )


# "**Parameter detection:** Variables read in the selected statements but defined
#  outside the selection become function parameters"
def test_a_variable_defined_outside_becomes_a_parameter(extract_function):
    source = "def main(n):\n    |print(n)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"].startswith("def show(n):\n    print(n)\n")


def test_a_variable_defined_inside_the_selection_is_not_a_parameter(extract_function):
    source = "def main():\n    |t = 1\n    print(t)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"] == (
        "def show():\n"
        "    t = 1\n"
        "    print(t)\n"
        "\n"
        "def main():\n"
        "    show()\n"
    )


# "ordered by first appearance in the selected code"
def test_parameters_follow_first_appearance(extract_function):
    source = "def main():\n    a = 1\n    b = 2\n    |print(b)\n    print(a)$\n"
    changed = extract_function(source, name="show").changed_files
    assert changed["sample.py"].startswith("def show(b, a):\n")


def test_a_variable_read_before_being_reassigned_is_a_parameter(extract_function):
    source = "def main():\n    total = 0\n    |total = total + 1$\n    print(total)\n"
    changed = extract_function(source, name="bump").changed_files
    assert changed["sample.py"].startswith("def bump(total):\n    total = total + 1\n")


# "**Return value detection:** Variables assigned in the selected statements and
#  used after the selection become return values. If one variable: `return var`."
def test_a_single_return_value_is_returned_plainly(extract_function):
    source = "def main():\n    a = 1\n    |total = a + 2$\n    print(total)\n"
    changed = extract_function(source, name="compute").changed_files
    assert changed["sample.py"] == (
        "def compute(a):\n"
        "    total = a + 2\n"
        "    return total\n"
        "\n"
        "def main():\n"
        "    a = 1\n"
        "    total = compute(a)\n"
        "    print(total)\n"
    )


def test_a_variable_not_used_afterwards_is_not_returned(extract_function):
    source = "def main():\n    a = 1\n    |total = a + 2$\n"
    changed = extract_function(source, name="compute").changed_files
    assert "return" not in changed["sample.py"]
    assert "    compute(a)\n" in changed["sample.py"]


# "If multiple: return a tuple in source order and update the call site to
#  tuple-unpack in the same order."
def test_two_return_values_come_back_as_a_tuple(extract_function):
    source = "def main():\n    a = 1\n    |b = a + 1\n    c = a + 2$\n    print(b, c)\n"
    changed = extract_function(source, name="compute").changed_files
    assert changed["sample.py"] == (
        "def compute(a):\n"
        "    b = a + 1\n"
        "    c = a + 2\n"
        "    return b, c\n"
        "\n"
        "def main():\n"
        "    a = 1\n"
        "    b, c = compute(a)\n"
        "    print(b, c)\n"
    )


# "If the selection is at module level (not inside a function), the new function
#  is inserted immediately before the first selected line."
def test_a_module_level_selection_inserts_above_itself(extract_function):
    source = "print('start')\n|value = 2 + 3$\nprint(value)\n"
    changed = extract_function(source, name="compute").changed_files
    assert changed["sample.py"] == (
        "print('start')\n"
        "def compute():\n"
        "    value = 2 + 3\n"
        "    return value\n"
        "\n"
        "value = compute()\n"
        "print(value)\n"
    )


# "The parameter-detection rule still applies at module level: if the selected
#  statements read a module-level name defined outside the selection, that name
#  becomes a parameter to the extracted function"
def test_a_module_level_read_becomes_a_parameter(extract_function):
    source = "base = 1\n|value = base + 2$\nprint(value)\n"
    changed = extract_function(source, name="compute").changed_files
    assert changed["sample.py"] == (
        "base = 1\n"
        "def compute(base):\n"
        "    value = base + 2\n"
        "    return value\n"
        "\n"
        "value = compute(base)\n"
        "print(value)\n"
    )


# "If it spans a partial statement, exit 1."
def test_half_of_a_multiline_statement_is_rejected(extract_function):
    source = "def main():\n    x = compute(\n        |1,\n        2)$\n"
    result = extract_function(source, name="show", expect_ok=False)
    assert result.returncode == 1
    assert result.stdout == ""


def test_the_first_line_of_a_multiline_statement_is_rejected(extract_function):
    source = "def main():\n    |x = compute($\n        1,\n        2)\n"
    assert extract_function(source, name="show", expect_ok=False).returncode == 1


# "`--name` must be a valid Python identifier. Exit 1 if not."
def test_an_invalid_name_is_rejected(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    assert extract_function(source, name="not a name", expect_ok=False).returncode == 1


def test_a_keyword_name_is_rejected(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    assert extract_function(source, name="return", expect_ok=False).returncode == 1


# "**Output format:** Same as `rename`."
def test_payload_has_changed_files_and_renames(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    payload = extract_function(source, name="show").payload
    assert set(payload) == {"changed_files", "renames"}


def test_diff_output_is_plain_text(extract_function):
    source = "def main():\n    x = 1\n    |print(x)$\n"
    stdout = extract_function(source, name="show", diff=True).stdout
    assert not stdout.startswith("{")
    assert "+def show(x):" in stdout
    assert "-    print(x)" in stdout


# "On error, print a message to STDERR and exit 1."
def test_extract_function_on_a_missing_file_fails(workdir):
    result = run_cli("extract-function", str(workdir / "missing.py"), 1, 0,
                     "--until", "1:3", "--name", "x")
    assert result.returncode == 1
    assert result.stdout == ""


# "The selection must span one or more complete statements (full lines)." A
# blank line or a comment is not a statement the selection could cut in half.
def test_blank_lines_around_the_selection_are_ignored(extract_function):
    source = "def main():\n    a = 1\n$\n    # work\n    b = a + 1\n|\n    print(b)\n"
    changed = extract_function(source, cursor=(3, 0), until=(6, 0), name="work").changed_files
    assert changed["sample.py"] == (
        "def work(a):\n"
        "    b = a + 1\n"
        "    return b\n"
        "\n"
        "def main():\n"
        "    a = 1\n"
        "\n"
        "    # work\n"
        "    b = work(a)\n"
        "\n"
        "    print(b)\n"
    )
