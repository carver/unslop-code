"""Spec section: Source Dialect Assumptions — the JSON Lines dialect."""

from conftest import column, header_of, rows_of


# Phrase: "JSONL: one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions.
def test_jsonl_object_per_line_becomes_a_row(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 2, "note": "bee"}, {"id": 1, "note": "ay"}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["1", "ay"], ["2", "bee"]]


# Phrase: "one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions, JSONL. Non-ASCII text survives.
def test_jsonl_utf8_values_are_preserved(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "note": "café"}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(result.stdout) == [["1", "café"]]


# Phrase: "blank/whitespace lines ignored"
# Context: Source Dialect Assumptions, JSONL.
def test_jsonl_blank_and_whitespace_lines_are_skipped(jsonl_file, run_tool):
    jsonl_file("a.jsonl", '\n{"id": 1}\n   \n\t\n{"id": 2}\n\n')
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: "keys case-sensitive"
# Context: Source Dialect Assumptions, JSONL. Differently cased keys are two columns.
def test_jsonl_keys_are_case_sensitive(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "Note": "upper", "note": "lower"}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert header_of(result.stdout) == ["Note", "id", "note"]
    assert rows_of(result.stdout) == [["upper", "1", "lower"]]


# Phrase: "null permitted"
# Context: Source Dialect Assumptions, JSONL; and Casting: null -> null literal.
def test_jsonl_null_is_emitted_as_the_null_literal(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "note": None}])
    result = run_tool(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.jsonl"
    )
    assert rows_of(result.stdout) == [["1", "NULL"]]


# Phrase: "Column set: union of all encountered field names"
# Context: Schema Resolution. A key absent from one object is null in that row.
def test_jsonl_objects_may_carry_different_keys(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "note": "a"}, {"id": 2, "amount": 3}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert header_of(result.stdout) == ["amount", "id", "note"]
    assert rows_of(result.stdout) == [["", "1", "a"], ["3", "2", ""]]


# Phrase: "objects must be flat (no arrays/objects as values)"
# Context: Source Dialect Assumptions; nested structures trigger error 6.
def test_jsonl_object_value_is_error_6(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "meta": {"k": "v"}}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 6
    assert result.stderr


# Phrase: "objects must be flat (no arrays/objects as values)"
# Context: Source Dialect Assumptions; an array value is nested too.
def test_jsonl_array_value_is_error_6(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "tags": ["x", "y"]}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 6
    assert result.stderr


# Phrase: "one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions. Ambiguity T30: a non-object line is malformed.
def test_jsonl_scalar_line_is_error_5(jsonl_file, run_tool):
    jsonl_file("a.jsonl", '{"id": 1}\n42\n')
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 5
    assert result.stderr


# Phrase: "one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions. Ambiguity T30: unparsable JSON is malformed.
def test_jsonl_invalid_json_line_is_error_5(jsonl_file, run_tool):
    jsonl_file("a.jsonl", '{"id": 1}\n{oops}\n')
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 5
    assert result.stderr


# Phrase: "For JSONL numbers, prefer int if integer and within range; otherwise float"
# Context: Casting. An integral number keeps its integer spelling.
def test_jsonl_integral_number_is_an_int(jsonl_file, csv_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "v": 5}])
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "string"}]}')
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl")
    assert column(result.stdout, "v") == ["5"]


# Phrase: "otherwise float"
# Context: Casting, JSONL numbers. A fractional number stays a float.
def test_jsonl_fractional_number_is_a_float(jsonl_file, csv_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "v": 5.0}, {"id": 2, "v": 2.5}])
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "string"}]}')
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl")
    assert column(result.stdout, "v") == ["5.0", "2.5"]


# Phrase: "prefer int if integer and within range; otherwise float"
# Context: Casting, JSONL numbers. Ambiguity T27: out of 64-bit range means float.
def test_jsonl_out_of_range_integer_becomes_a_float(jsonl_file, csv_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "v": 2**70}])
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "string"}]}')
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl")
    assert column(result.stdout, "v") == [repr(float(2**70))]


# Phrase: "JSONL values come typed (string/number/bool/null)"
# Context: Casting. A JSON boolean renders canonically.
def test_jsonl_boolean_values_render_as_true_and_false(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "ok": True}, {"id": 2, "ok": False}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert column(result.stdout, "ok") == ["true", "false"]


# Phrase: "JSONL values come typed ... Apply target output schema cast rules to every cell"
# Context: Casting. A typed number cast to a declared string column keeps its digits.
def test_jsonl_number_cast_to_declared_int(jsonl_file, csv_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 2}, {"id": 10}])
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}]}')
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl")
    assert column(result.stdout, "id") == ["2", "10"]


# Phrase: "On cast failure, follow --on-type-error"
# Context: Casting. A JSONL string that is not a number fails an int column.
def test_jsonl_cast_failure_follows_the_policy(jsonl_file, csv_file, run_tool):
    jsonl_file("a.jsonl", [{"id": "abc"}])
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}]}')
    coerced = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.jsonl",
    )
    kept = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "keep-string", "a.jsonl",
    )
    failed = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert rows_of(coerced.stdout) == [[""]]
    assert rows_of(kept.stdout) == [["abc"]]
    assert failed.returncode != 0
