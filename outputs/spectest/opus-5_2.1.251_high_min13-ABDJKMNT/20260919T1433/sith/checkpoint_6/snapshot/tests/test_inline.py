"""Spec: New Subcommands / `inline`."""


# Spec: "python sith.py inline <file> <line> <col> [--diff] [--project <dir>]"
def test_inline_subcommand_is_accepted(inline):
    result = inline("val$ue = compute()\nprint(value)\n")
    assert result.code == 0


# Spec: "Inline a variable - replace all references with the variable's value
# and delete the definition."
def test_reference_is_replaced_and_definition_deleted(inline):
    result = inline("val$ue = compute()\nprint(value)\n")
    assert result.changed_files == {"module_under_test.py": "print(compute())\n"}


# Spec: "replace all references with the variable's value"
def test_every_reference_is_replaced(inline):
    result = inline("val$ue = 3\nfirst = value\nsecond = value\n")
    assert result.changed_files == {"module_under_test.py": "first = 3\nsecond = 3\n"}


# Spec: "Inline a variable" - the cursor may sit on a reference to it.
def test_inline_started_from_a_reference(inline):
    result = inline("value = 3\nprint(val$ue)\n")
    assert result.changed_files == {"module_under_test.py": "print(3)\n"}


# Spec: "Wrap the inlined expression in parentheses when needed to preserve
# evaluation order"
def test_expression_is_parenthesised_where_precedence_demands_it(inline):
    result = inline("tot$al = a + b\nscaled = total * 2\n")
    assert result.changed_files == {"module_under_test.py": "scaled = (a + b) * 2\n"}


# Spec: "Parenthesis insertion for `inline` is required whenever dropping
# parentheses would change operator precedence in the transformed code."
def test_no_parentheses_where_precedence_is_unchanged(inline):
    result = inline("tot$al = a + b\nshifted = total + 2\n")
    assert result.changed_files == {"module_under_test.py": "shifted = a + b + 2\n"}


# Spec: "Wrap the inlined expression in parentheses when needed"
def test_atomic_value_is_never_parenthesised(inline):
    result = inline("val$ue = compute()\nscaled = value * 2\n")
    assert result.changed_files == {"module_under_test.py": "scaled = compute() * 2\n"}


# Spec: "Cannot inline function or class definitions - exit 1 with
# "cannot inline a function/class definition"."
def test_function_definition_cannot_be_inlined(inline):
    result = inline("def hel$per():\n    pass\n\nhelper()\n")
    assert result.code == 1
    assert "cannot inline a function/class definition" in result.stderr
    assert result.stdout == ""


# Spec: "Cannot inline function or class definitions"
def test_class_definition_cannot_be_inlined(inline):
    result = inline("class Sha$pe:\n    pass\n\nShape()\n")
    assert result.code == 1
    assert "cannot inline a function/class definition" in result.stderr


# Spec: "The name must have at least one reference beyond the definition. If the
# name is unused, exit 1 with "name has no references to inline"."
def test_unused_name_cannot_be_inlined(inline):
    result = inline("val$ue = 3\n")
    assert result.code == 1
    assert "name has no references to inline" in result.stderr
    assert result.stdout == ""


# Spec: "The name must be a simple assignment (`x = <expr>`)."
def test_parameter_cannot_be_inlined(inline):
    result = inline("def outer(val$ue):\n    return value\n")
    assert result.code == 1
    assert result.stdout == ""


# Spec: "Output format: Same as `rename` - `changed_files` (JSON) or unified
# diff (`--diff`)."
def test_diff_output_shows_the_inlined_value(inline):
    result = inline("val$ue = 3\nprint(value)\n", diff=True)
    assert result.code == 0
    assert "-value = 3" in result.stdout
    assert "+print(3)" in result.stdout


# Spec: "delete the definition" - the lines around it are left alone.
def test_only_the_definition_line_is_deleted(inline):
    result = inline("before = 1\nval$ue = 3\nafter = value\n")
    assert result.changed_files == {"module_under_test.py": "before = 1\nafter = 3\n"}
