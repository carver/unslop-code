"""Spec: New Subcommands / `extract-function`."""


# Spec: "python sith.py extract-function <file> <line> <col> --until <line>:<col>
# --name <name>"
def test_extract_function_subcommand_is_accepted(extract_function):
    source = "def outer():\n    a = 1\n$    print(a)~\n"
    assert extract_function(source, "report").code == 0


# Spec: "Extract the code from <line>:<col> to --until <line>:<col> into a new
# function." and "The new function is inserted immediately before the
# function/class containing the selection, at the same indentation level as the
# enclosing function."
def test_statements_move_into_a_function_before_the_enclosing_one(extract_function):
    source = "def outer():\n    a = 1\n$    print(a)~\n    return a\n"
    assert extract_function(source, "report").changed_files == {
        "module_under_test.py":
            "def report(a):\n"
            "    print(a)\n"
            "\n"
            "def outer():\n"
            "    a = 1\n"
            "    report(a)\n"
            "    return a\n"
    }


# Spec: "Parameter detection: Variables read in the selected statements but
# defined outside the selection become function parameters, ordered by first
# appearance in the selected code."
def test_parameters_follow_first_appearance_in_the_selection(extract_function):
    source = (
        "def outer():\n"
        "    first = 1\n"
        "    second = 2\n"
        "$    print(second)\n"
        "    print(first)~\n"
    )
    assert extract_function(source, "report").changed_files == {
        "module_under_test.py":
            "def report(second, first):\n"
            "    print(second)\n"
            "    print(first)\n"
            "\n"
            "def outer():\n"
            "    first = 1\n"
            "    second = 2\n"
            "    report(second, first)\n"
    }


# Spec: "Return value detection: Variables assigned in the selected statements
# and used after the selection become return values. If one variable:
# `return var`."
def test_single_return_value_is_returned_and_assigned(extract_function):
    source = "def outer():\n    a = 1\n$    total = a + 2~\n    return total\n"
    assert extract_function(source, "compute").changed_files == {
        "module_under_test.py":
            "def compute(a):\n"
            "    total = a + 2\n"
            "    return total\n"
            "\n"
            "def outer():\n"
            "    a = 1\n"
            "    total = compute(a)\n"
            "    return total\n"
    }


# Spec: "If multiple: return a tuple in source order and update the call site to
# tuple-unpack in the same order."
def test_multiple_return_values_are_tuple_unpacked(extract_function):
    source = (
        "def outer():\n"
        "$    left = 1\n"
        "    right = 2~\n"
        "    return left + right\n"
    )
    assert extract_function(source, "prepare").changed_files == {
        "module_under_test.py":
            "def prepare():\n"
            "    left = 1\n"
            "    right = 2\n"
            "    return left, right\n"
            "\n"
            "def outer():\n"
            "    left, right = prepare()\n"
            "    return left + right\n"
    }


# Spec: "Variables assigned in the selected statements and used after the
# selection become return values." - one that is never read again does not.
def test_value_unused_after_the_selection_is_not_returned(extract_function):
    source = "def outer():\n$    scratch = 1~\n    return 2\n"
    assert extract_function(source, "prepare").changed_files == {
        "module_under_test.py":
            "def prepare():\n"
            "    scratch = 1\n"
            "\n"
            "def outer():\n"
            "    prepare()\n"
            "    return 2\n"
    }


# Spec: "If the selection is at module level (not inside a function), the new
# function is inserted immediately before the first selected line."
def test_module_level_selection_inserts_the_function_in_place(extract_function):
    source = "start = 1\n$print(start)~\nend = 2\n"
    assert extract_function(source, "report").changed_files == {
        "module_under_test.py":
            "start = 1\n"
            "def report(start):\n"
            "    print(start)\n"
            "\n"
            "report(start)\n"
            "end = 2\n"
    }


# Spec: "if the selected statements read a module-level name defined outside the
# selection, that name becomes a parameter to the extracted function rather than
# staying an implicit global in the extracted body."
def test_module_level_name_becomes_a_parameter(extract_function):
    source = "limit = 10\n$total = limit * 2~\nprint(total)\n"
    changed = extract_function(source, "compute").changed_files["module_under_test.py"]
    assert changed.startswith("limit = 10\ndef compute(limit):\n    total = limit * 2\n    return total\n")


# Spec: "The selection must span one or more complete statements (full lines).
# If it spans a partial statement, exit 1."
def test_partial_statement_exits_one(extract_function):
    source = "def outer():\n    total = $1 + 2~\n    return total\n"
    result = extract_function(source, "compute")
    assert result.code == 1
    assert result.stdout == ""


# Spec: "The selection must span one or more complete statements"
def test_selection_ending_mid_statement_exits_one(extract_function):
    source = "def outer():\n$    first = 1\n    second = 2~2\n    return first\n"
    assert extract_function(source, "compute").code == 1


# Spec: "--name must be a valid Python identifier. Exit 1 if not."
def test_invalid_name_exits_one(extract_function):
    source = "def outer():\n    a = 1\n$    print(a)~\n"
    result = extract_function(source, "not a name")
    assert result.code == 1
    assert result.stdout == ""


# Spec: "Output format: Same as `rename`."
def test_diff_output_is_available(extract_function):
    source = "def outer():\n    a = 1\n$    print(a)~\n"
    result = extract_function(source, "report", diff=True)
    assert "+def report(a):" in result.stdout
    assert "-    print(a)" in result.stdout
