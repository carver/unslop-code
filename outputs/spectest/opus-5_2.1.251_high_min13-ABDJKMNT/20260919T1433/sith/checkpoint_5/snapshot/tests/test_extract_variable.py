"""Spec: New Subcommands / `extract-variable`."""


# Spec: "python sith.py extract-variable <file> <line> <col> --until <line>:<col>
# --name <name>"
def test_extract_variable_subcommand_is_accepted(extract_variable):
    result = extract_variable("result = $compute(3)~ + 1\n", "value")
    assert result.code == 0


# Spec: "Extract the expression from <line>:<col> to --until <line>:<col> into a
# new variable." and "The original expression is replaced with the variable name."
def test_expression_is_replaced_by_the_new_variable(extract_variable):
    result = extract_variable("result = $compute(3)~ + 1\n", "value")
    assert result.changed_files == {
        "module_under_test.py": "value = compute(3)\nresult = value + 1\n"
    }


# Spec: "The new assignment is inserted on the line immediately before the
# statement containing the expression, at the same indentation level."
def test_assignment_keeps_the_indentation_of_its_statement(extract_variable):
    source = "def outer():\n    result = $compute(3)~ + 1\n    return result\n"
    assert extract_variable(source, "value").changed_files == {
        "module_under_test.py":
            "def outer():\n    value = compute(3)\n    result = value + 1\n    return result\n"
    }


# Spec: "inserted on the line immediately before the statement containing the
# expression" - the statement, not the expression's own line.
def test_assignment_goes_before_the_whole_statement(extract_variable):
    source = "if $len(items)~ > 2:\n    handle()\n"
    assert extract_variable(source, "size").changed_files == {
        "module_under_test.py": "size = len(items)\nif size > 2:\n    handle()\n"
    }


# Spec: "The selection must span a complete expression. If the selection cuts
# across an expression boundary ... exit 1 with "selection is not a complete
# expression"."
def test_partial_expression_exits_one(extract_variable):
    result = extract_variable("result = $compute(3~) + 1\n", "value")
    assert result.code == 1
    assert "selection is not a complete expression" in result.stderr
    assert result.stdout == ""


# Spec: "--name must be a valid Python identifier. Exit 1 if not."
def test_invalid_name_exits_one(extract_variable):
    result = extract_variable("result = $compute(3)~ + 1\n", "not a name")
    assert result.code == 1
    assert result.stdout == ""


# Spec: "Output format: Same as `rename`."
def test_diff_output_is_available(extract_variable):
    result = extract_variable("result = $compute(3)~ + 1\n", "value", diff=True)
    assert result.code == 0
    assert "+value = compute(3)" in result.stdout
    assert "+result = value + 1" in result.stdout
