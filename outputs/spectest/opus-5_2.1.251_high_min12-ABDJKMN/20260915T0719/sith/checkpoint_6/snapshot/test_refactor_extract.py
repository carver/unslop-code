"""`extract-variable` / `extract-function` -- spec: New Subcommands."""

import json


# ---------------------------------------------------------------------------
# "python sith.py extract-variable <file> <line> <col> --until <line>:<col>
#  --name <name> [--diff] [--project <dir>]"
# ---------------------------------------------------------------------------

def test_extract_variable_accepts_the_documented_argument_shape(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-variable", tmp_path, {
        "main.py": "x = 1 + <|>2 * 3<^>\n",
    }, ["--name", "part"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) >= {"changed_files", "renames"}


# ---------------------------------------------------------------------------
# "Extract the expression from <line>:<col> to --until <line>:<col> into a new
#  variable." / "The original expression is replaced with the variable name."
# ---------------------------------------------------------------------------

def test_extract_variable_replaces_the_selection_with_the_name(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "x = 1 + <|>2 * 3<^>\n",
    }, ["--name", "part"])
    assert out["main.py"] == "part = 2 * 3\nx = 1 + part\n"


def test_extract_variable_of_a_whole_right_hand_side(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "x = <|>compute(1, 2)<^>\n",
    }, ["--name", "value"])
    assert out["main.py"] == "value = compute(1, 2)\nx = value\n"


def test_extract_variable_of_a_call_argument(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "print(<|>a + b<^>, c)\n",
    }, ["--name", "total"])
    assert out["main.py"] == "total = a + b\nprint(total, c)\n"


def test_extract_variable_of_an_attribute_chain(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "y = <|>obj.attr.value<^> + 1\n",
    }, ["--name", "v"])
    assert out["main.py"] == "v = obj.attr.value\ny = v + 1\n"


# ---------------------------------------------------------------------------
# "The new assignment is inserted on the line immediately before the statement
#  containing the expression, at the same indentation level."
# ---------------------------------------------------------------------------

def test_new_assignment_goes_immediately_before_the_statement(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "A = 0\nx = 1 + <|>2 * 3<^>\nB = 4\n",
    }, ["--name", "part"])
    assert out["main.py"] == "A = 0\npart = 2 * 3\nx = 1 + part\nB = 4\n"


def test_new_assignment_matches_the_statement_indentation(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "def f(a, b):\n    return <|>a + b<^>\n",
    }, ["--name", "total"])
    assert out["main.py"] == ("def f(a, b):\n    total = a + b\n"
                             "    return total\n")


def test_new_assignment_matches_a_deeper_indentation(rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "def f(a, b):\n    if a:\n        return <|>a + b<^>\n",
    }, ["--name", "total"])
    assert out["main.py"] == ("def f(a, b):\n    if a:\n"
                              "        total = a + b\n"
                              "        return total\n")


def test_extraction_inside_a_multiline_statement_precedes_that_statement(
        rhelpers, tmp_path):
    out = rhelpers.changed("extract-variable", tmp_path, {
        "main.py": "x = call(\n    <|>a + b<^>,\n    c,\n)\n",
    }, ["--name", "total"])
    assert out["main.py"] == ("total = a + b\nx = call(\n    total,\n    c,\n)\n")


# ---------------------------------------------------------------------------
# "The selection must span a complete expression. If the selection cuts across
#  an expression boundary (e.g., selects half a function call), exit 1 with
#  'selection is not a complete expression'."
# ---------------------------------------------------------------------------

def test_partial_call_selection_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-variable", tmp_path, {
        "main.py": "x = <|>foo(1<^>) + bar(2)\n",
    }, ["--name", "part"])
    assert r.returncode == 1
    assert "selection is not a complete expression" in (r.stderr + r.stdout)


def test_selection_spanning_an_operator_boundary_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-variable", tmp_path, {
        "main.py": "x = a + <|>b + <^>c\n",
    }, ["--name", "part"])
    assert r.returncode == 1


def test_selection_starting_mid_identifier_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-variable", tmp_path, {
        "main.py": "x = al<|>pha<^> + beta\n",
    }, ["--name", "part"])
    assert r.returncode == 1


def test_incomplete_selection_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-variable", tmp_path, {
        "main.py": "x = <|>foo(1<^>) + bar(2)\n",
    }, ["--name", "part"])
    assert "changed_files" not in r.stdout


# ---------------------------------------------------------------------------
# "`--name` must be a valid Python identifier. Exit 1 if not."
# ---------------------------------------------------------------------------

def test_extract_variable_rejects_an_invalid_name(rhelpers, tmp_path):
    for bad in ("1abc", "with-dash", "def", "a b"):
        r = rhelpers.refactor_raw("extract-variable", tmp_path, {
            "main.py": "x = 1 + <|>2 * 3<^>\n",
        }, ["--name", bad])
        assert r.returncode == 1, "accepted %r" % bad


# ---------------------------------------------------------------------------
# "**Output format:** Same as `rename`."
# ---------------------------------------------------------------------------

def test_extract_variable_diff_is_plain_text(rhelpers, tmp_path):
    out = rhelpers.diff_text("extract-variable", tmp_path, {
        "main.py": "x = 1 + <|>2 * 3<^>\n",
    }, ["--name", "part"])
    try:
        json.loads(out)
    except ValueError:
        pass
    else:
        raise AssertionError("--diff emitted JSON: %r" % out)
    assert "@@" in out
    assert "+part = 2 * 3" in out


def test_extract_variable_reports_empty_renames(rhelpers, tmp_path):
    payload = rhelpers.refactor("extract-variable", tmp_path, {
        "main.py": "x = 1 + <|>2 * 3<^>\n",
    }, ["--name", "part"])
    assert payload["renames"] == {}
    assert list(payload["changed_files"]) == ["main.py"]


# ===========================================================================
# extract-function
# ===========================================================================

# ---------------------------------------------------------------------------
# "python sith.py extract-function <file> <line> <col> --until <line>:<col>
#  --name <name> [--diff] [--project <dir>]"
# ---------------------------------------------------------------------------

def test_extract_function_accepts_the_documented_argument_shape(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert set(json.loads(r.stdout)) >= {"changed_files", "renames"}


# ---------------------------------------------------------------------------
# "The new function is inserted immediately before the function/class
#  containing the selection, at the same indentation level as the enclosing
#  function."
# ---------------------------------------------------------------------------

def _lines(text):
    return [ln for ln in text.split("\n")]


def test_extracted_function_precedes_the_enclosing_function(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert body.index("def helper(") < body.index("def f(")


def test_extracted_function_is_at_module_indentation(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert body.startswith("def helper(")


def test_extracted_function_of_a_method_matches_method_indentation(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "class C:\n    def m(self):\n        <|>a = 1\n"
                   "        b = a + 1<^>\n        return b\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert "\n    def helper(" in body
    assert body.index("def helper(") < body.index("def m(")


# ---------------------------------------------------------------------------
# "**Parameter detection:** Variables read in the selected statements but
#  defined outside the selection become function parameters, ordered by first
#  appearance in the selected code."
# ---------------------------------------------------------------------------

def test_outside_variable_read_inside_becomes_a_parameter(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    assert "def helper(a):" in out["main.py"]


def test_parameters_follow_first_appearance_order(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    p = 1\n    q = 2\n"
                   "    <|>r = q + p\n    s = r + p<^>\n    return s\n",
    }, ["--name", "helper"])
    assert "def helper(q, p):" in out["main.py"]


def test_a_variable_defined_inside_the_selection_is_not_a_parameter(
        rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    assert "def helper():" in out["main.py"]


def test_the_call_site_passes_the_parameters(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    assert "helper(a)" in out["main.py"]


# ---------------------------------------------------------------------------
# "**Return value detection:** Variables assigned in the selected statements
#  and used after the selection become return values. If one variable:
#  `return var`."
# ---------------------------------------------------------------------------

def test_single_return_value(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert "    return b\n" in body
    assert "    b = helper(a)\n" in body


def test_no_return_when_nothing_is_used_afterwards(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    print(a)<^>\n    return 0\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert "    helper()\n" in body
    assert "return a" not in body


# ---------------------------------------------------------------------------
# "If multiple: return a tuple in source order and update the call site to
#  tuple-unpack in the same order."
# ---------------------------------------------------------------------------

def test_multiple_return_values_are_returned_as_a_tuple(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = 2<^>\n    return a + b\n",
    }, ["--name", "helper"])
    assert "    return a, b\n" in out["main.py"]


def test_call_site_tuple_unpacks_in_the_same_order(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = 2<^>\n    return a + b\n",
    }, ["--name", "helper"])
    assert "    a, b = helper()\n" in out["main.py"]


# ---------------------------------------------------------------------------
# "If the selection is at module level (not inside a function), the new
#  function is inserted immediately before the first selected line."
# ---------------------------------------------------------------------------

def test_module_level_extraction_inserts_before_the_first_selected_line(
        rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "HEAD = 0\n<|>a = 1\nb = a + 1<^>\nprint(b)\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert body.startswith("HEAD = 0\ndef helper(")
    assert "b = helper()" in body


# ---------------------------------------------------------------------------
# "The parameter-detection rule still applies at module level: if the selected
#  statements read a module-level name defined outside the selection, that name
#  becomes a parameter to the extracted function rather than staying an
#  implicit global in the extracted body."
# ---------------------------------------------------------------------------

def test_module_level_read_becomes_a_parameter(rhelpers, tmp_path):
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "BASE = 10\n<|>total = BASE + 1<^>\nprint(total)\n",
    }, ["--name", "helper"])
    body = out["main.py"]
    assert "def helper(BASE):" in body
    assert "total = helper(BASE)" in body


# ---------------------------------------------------------------------------
# "The selection must span one or more complete statements (full lines). If it
#  spans a partial statement, exit 1."
# ---------------------------------------------------------------------------

def test_partial_statement_selection_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-function", tmp_path, {
        "main.py": "def f():\n    a = <|>1 + 2<^>\n    return a\n",
    }, ["--name", "helper"])
    assert r.returncode == 1


def test_selection_stopping_mid_statement_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-function", tmp_path, {
        "main.py": "def f():\n    <|>a = 1\n    b = 2 +<^> 3\n    return b\n",
    }, ["--name", "helper"])
    assert r.returncode == 1


def test_extract_function_partial_selection_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("extract-function", tmp_path, {
        "main.py": "def f():\n    a = <|>1 + 2<^>\n    return a\n",
    }, ["--name", "helper"])
    assert "changed_files" not in r.stdout


# ---------------------------------------------------------------------------
# "`--name` must be a valid Python identifier. Exit 1 if not."
# ---------------------------------------------------------------------------

def test_extract_function_rejects_an_invalid_name(rhelpers, tmp_path):
    for bad in ("1abc", "with-dash", "class", "a b"):
        r = rhelpers.refactor_raw("extract-function", tmp_path, {
            "main.py": "def f():\n    <|>a = 1\n    b = a + 1<^>\n    return b\n",
        }, ["--name", bad])
        assert r.returncode == 1, "accepted %r" % bad


# ---------------------------------------------------------------------------
# "**Output format:** Same as `rename`."
# ---------------------------------------------------------------------------

def test_extract_function_diff_is_plain_text(rhelpers, tmp_path):
    out = rhelpers.diff_text("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    try:
        json.loads(out)
    except ValueError:
        pass
    else:
        raise AssertionError("--diff emitted JSON: %r" % out)
    assert "@@" in out
    assert any("def helper(a):" in ln for ln in rhelpers.added(out))


def test_extract_function_reports_empty_renames(rhelpers, tmp_path):
    payload = rhelpers.refactor("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1<^>\n    return b\n",
    }, ["--name", "helper"])
    assert payload["renames"] == {}
    assert list(payload["changed_files"]) == ["main.py"]


def test_extracted_code_remains_parseable(rhelpers, tmp_path):
    import ast
    out = rhelpers.changed("extract-function", tmp_path, {
        "main.py": "def f():\n    a = 1\n    <|>b = a + 1\n    c = b * 2<^>\n"
                   "    return b + c\n",
    }, ["--name", "helper"])
    ast.parse(out["main.py"])
