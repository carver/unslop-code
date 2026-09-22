"""`inline` -- spec: New Subcommands / inline."""

import json


# ---------------------------------------------------------------------------
# "python sith.py inline <file> <line> <col> [--diff] [--project <dir>]"
# ---------------------------------------------------------------------------

def test_inline_accepts_the_documented_argument_shape(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    })
    assert r.returncode == 0, "stderr=%r" % r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) >= {"changed_files", "renames"}


# ---------------------------------------------------------------------------
# "Inline a variable -- replace all references with the variable's value and
#  delete the definition."
# ---------------------------------------------------------------------------

def test_inline_replaces_the_reference_and_drops_the_definition(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "x<|> = compute()\nprint(x)\n",
    })
    assert out["main.py"] == "print(compute())\n"


def test_inline_replaces_every_reference(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "n<|> = 5\nprint(n)\nprint(n + 1)\nq = n\n",
    })
    assert out["main.py"] == "print(5)\nprint(5 + 1)\nq = 5\n"


def test_inline_inside_a_function_body(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "def f(a):\n    tm<|>p = a * 2\n    return tmp\n",
    })
    assert out["main.py"] == "def f(a):\n    return a * 2\n"


def test_inline_from_a_reference_rather_than_the_definition(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "x = compute()\nprint(x<|>)\n",
    })
    assert out["main.py"] == "print(compute())\n"


def test_inline_keeps_surrounding_lines_intact(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "A = 0\nx<|> = 7\nB = 2\nprint(x)\n",
    })
    assert out["main.py"] == "A = 0\nB = 2\nprint(7)\n"


def test_inline_of_a_call_expression(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "def g():\n    return 1\n\nva<|>l = g()\nprint(val)\n",
    })
    assert out["main.py"] == "def g():\n    return 1\n\nprint(g())\n"


# ---------------------------------------------------------------------------
# "Wrap the inlined expression in parentheses when needed to preserve
#  evaluation order" / "Parenthesis insertion for `inline` is required
#  whenever dropping parentheses would change operator precedence."
# ---------------------------------------------------------------------------

def test_sum_inlined_into_a_product_is_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\ns<|> = a + b\ny = s * 3\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = (a + b) * 3\n"


def test_product_inlined_into_a_sum_is_not_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\np<|> = a * b\ny = p + 3\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = a * b + 3\n"


def test_atom_is_never_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nx<|> = a\ny = x * 3\n",
    })
    assert out["main.py"] == "a = 1\ny = a * 3\n"


def test_sum_inlined_as_a_whole_statement_value_is_not_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\ns<|> = a + b\ny = s\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = a + b\n"


def test_sum_inlined_as_a_call_argument_is_not_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\ns<|> = a + b\nprint(s)\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\nprint(a + b)\n"


def test_subtraction_on_the_right_of_a_subtraction_is_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\nd<|> = a - b\ny = 10 - d\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = 10 - (a - b)\n"


def test_boolean_inlined_under_not_is_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\nc<|> = a or b\ny = not c\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = not (a or b)\n"


def test_sum_used_as_an_attribute_receiver_is_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "a = 1\nb = 2\ns<|> = a + b\ny = s.bit_length()\n",
    })
    assert out["main.py"] == "a = 1\nb = 2\ny = (a + b).bit_length()\n"


def test_call_used_as_an_attribute_receiver_is_not_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "def g():\n    return 1\n\nv<|> = g()\ny = v.bit_length()\n",
    })
    assert out["main.py"] == ("def g():\n    return 1\n\ny = g().bit_length()\n")


def test_lambda_inlined_into_a_call_position_is_parenthesised(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "f<|> = lambda: 1\ny = f()\n",
    })
    assert out["main.py"] == "y = (lambda: 1)()\n"


# ---------------------------------------------------------------------------
# "Cannot inline function or class definitions -- exit 1 with
#  'cannot inline a function/class definition'."
# ---------------------------------------------------------------------------

def test_inline_on_a_function_definition_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "def f<|>():\n    pass\n\nf()\n",
    })
    assert r.returncode == 1
    assert "cannot inline a function/class definition" in (r.stderr + r.stdout)


def test_inline_on_a_class_definition_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "class C<|>:\n    pass\n\nC()\n",
    })
    assert r.returncode == 1
    assert "cannot inline a function/class definition" in (r.stderr + r.stdout)


def test_inline_on_a_function_definition_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "def f<|>():\n    pass\n\nf()\n",
    })
    assert "changed_files" not in r.stdout


# ---------------------------------------------------------------------------
# "The name must have at least one reference beyond the definition. If the
#  name is unused, exit 1 with 'name has no references to inline'."
# ---------------------------------------------------------------------------

def test_unused_name_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "x<|> = 1\n",
    })
    assert r.returncode == 1
    assert "name has no references to inline" in (r.stderr + r.stdout)


def test_unused_local_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "def f():\n    unu<|>sed = 1\n    return 2\n",
    })
    assert r.returncode == 1


def test_unused_name_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "x<|> = 1\n",
    })
    assert "changed_files" not in r.stdout


# ---------------------------------------------------------------------------
# "The name must be a simple assignment (`x = <expr>`)."
# ---------------------------------------------------------------------------

def test_inline_on_an_import_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "import o<|>s\nprint(os)\n",
    })
    assert r.returncode == 1


def test_inline_on_a_parameter_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "def f(a<|>):\n    return a\n",
    })
    assert r.returncode == 1


def test_inline_on_a_for_loop_target_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "for i<|> in range(3):\n    print(i)\n",
    })
    assert r.returncode == 1


def test_inline_of_a_name_assigned_twice_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "x<|> = 1\nx = 2\nprint(x)\n",
    })
    assert r.returncode == 1


def test_cursor_not_on_a_name_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("inline", tmp_path, {
        "main.py": "x = 1 <|>+ 2\nprint(x)\n",
    })
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# "**Output format:** Same as `rename` -- `changed_files` (JSON) or unified
#  diff (`--diff`)."
# ---------------------------------------------------------------------------

def test_inline_diff_is_plain_text(rhelpers, tmp_path):
    out = rhelpers.diff_text("inline", tmp_path, {
        "main.py": "x<|> = compute()\nprint(x)\n",
    })
    try:
        json.loads(out)
    except ValueError:
        pass
    else:
        raise AssertionError("--diff emitted JSON: %r" % out)
    assert "@@" in out
    assert "-x = compute()" in out
    assert "+print(compute())" in out


def test_inline_reports_renames_as_empty(rhelpers, tmp_path):
    payload = rhelpers.refactor("inline", tmp_path, {
        "main.py": "x<|> = compute()\nprint(x)\n",
    })
    assert payload["renames"] == {}


def test_inline_only_lists_the_changed_file(rhelpers, tmp_path):
    out = rhelpers.changed("inline", tmp_path, {
        "main.py": "x<|> = compute()\nprint(x)\n",
        "other.py": "y = 2\n",
    })
    assert list(out) == ["main.py"]
