"""Spec section: Source Dialect Assumptions — JSONL, and its casting rules."""
from conftest import column, table


# Phrase: "JSONL: one UTF-8 JSON object per line"
def test_one_object_per_line(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 2, "v": "y"}, {"id": 1, "v": "x"}])
    res = run("--output", "-", "--key", "id", "a.jsonl")
    assert table(res.stdout) == [["id", "v"], ["1", "x"], ["2", "y"]]


# Phrase: "JSONL: ... blank/whitespace lines ignored"
def test_blank_and_whitespace_lines_ignored(run, text_file):
    text_file("a.jsonl", '\n{"id": 1}\n   \n\t\n{"id": 2}\n\n')
    res = run("--output", "-", "--key", "id", "a.jsonl")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "id") == ["1", "2"]


# Phrase: "JSONL: ... keys case-sensitive"
# Context: Id and id are two distinct columns.
def test_keys_are_case_sensitive(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "Id": 9}])
    assert table(run("--output", "-", "--key", "id", "a.jsonl").stdout)[0] == ["Id", "id"]


# Phrase: "Column set: union of all encountered field names"
# Context: T34 — lines need not carry the same keys; absent keys are null.
def test_field_names_union_across_lines(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "a": "p"}, {"id": 2, "b": "q"}])
    res = run("--output", "-", "--key", "id", "a.jsonl")
    assert table(res.stdout) == [["a", "b", "id"], ["p", "", "1"], ["", "q", "2"]]


# Phrase: "JSONL: ... null permitted" / "If JSONL/Parquet value is null ... emit null literal"
def test_json_null_becomes_the_null_literal(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": None}])
    res = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.jsonl")
    assert column(res.stdout, "v") == ["NA"]


# Phrase: "objects must be flat (no arrays/objects as values)" / "nested structures trigger error 6"
def test_array_value_is_error_6(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2]}])
    res = run("--output", "-", "--key", "id", "a.jsonl")
    assert res.returncode == 6
    assert res.stderr.strip().startswith("ERR 6 ")


# Phrase: "objects must be flat (no arrays/objects as values)"
def test_object_value_is_error_6(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": {"k": 2}}])
    assert run("--output", "-", "--key", "id", "a.jsonl").returncode == 6


# Phrase: "one UTF-8 JSON object per line"
# Context: T28 — a syntax error is malformed source data, not a nested structure.
def test_unparseable_line_is_error_5(run, text_file):
    text_file("a.jsonl", '{"id": 1}\n{"id": \n')
    assert run("--output", "-", "--key", "id", "a.jsonl").returncode == 5


# Phrase: "one UTF-8 JSON object per line"
# Context: T28 — a top-level array violates "object per line" (error 5).
def test_top_level_array_line_is_error_5(run, text_file):
    text_file("a.jsonl", '{"id": 1}\n[1, 2]\n')
    assert run("--output", "-", "--key", "id", "a.jsonl").returncode == 5


# Phrase: "JSONL values come typed (string/number/bool/null)"
# Context: T31 — a JSON string stays a string column even when it spells a number.
def test_json_string_column_infers_as_string(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": "10"}, {"id": "9"}])
    assert column(run("--output", "-", "--key", "id", "a.jsonl").stdout, "id") == ["10", "9"]


# Phrase: "For JSONL numbers, prefer int if integer and within range"
# Context: T30 — 3.0 is integral, so the column is int and renders without a decimal.
def test_integral_json_floats_prefer_int(run, jsonl_file):
    jsonl_file("a.jsonl", [{"n": 3.0}, {"n": 10}])
    assert column(run("--output", "-", "--key", "n", "a.jsonl").stdout, "n") == ["3", "10"]


# Phrase: "For JSONL numbers ... otherwise float"
def test_non_integral_json_numbers_are_float(run, jsonl_file):
    jsonl_file("a.jsonl", [{"n": 1.5}, {"n": 2}])
    assert column(run("--output", "-", "--key", "n", "a.jsonl").stdout, "n") == ["1.5", "2.0"]


# Phrase: "JSONL values come typed (string/number/bool/null)"
# Context: a JSON bool renders in the tool's canonical bool spelling (T4).
def test_json_bool_renders_canonically(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "b": True}, {"id": 2, "b": False}])
    assert column(run("--output", "-", "--key", "id", "a.jsonl").stdout, "b") == ["true", "false"]


# Phrase: "Apply target output schema cast rules to every cell"
# Context: T29 — a typed JSON value is cast by the schema's rules, not Python's;
#   1.7 does not truncate into an int column.
def test_non_integral_number_into_int_column_fails_the_cast(run, jsonl_file, schema_file):
    jsonl_file("a.jsonl", [{"id": 1, "n": 1.7}])
    schema = schema_file([("id", "int"), ("n", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.jsonl")
    assert column(res.stdout, "n") == [""]


# Phrase: "Apply target output schema cast rules to every cell"
# Context: a JSON number cast to a string column renders as its canonical text.
def test_number_into_string_column(run, jsonl_file, schema_file):
    jsonl_file("a.jsonl", [{"id": 1, "n": 42}])
    schema = schema_file([("id", "int"), ("n", "string")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.jsonl")
    assert column(res.stdout, "n") == ["42"]


# Phrase: "JSONL: one UTF-8 JSON object per line"
# Context: non-ASCII text survives the round trip.
def test_utf8_values(run, text_file):
    text_file("a.jsonl", '{"id": 1, "v": "café"}\n')
    assert column(run("--output", "-", "--key", "id", "a.jsonl").stdout, "v") == ["café"]


# Phrase: "If JSONL/Parquet value is null or CSV/TSV cell is empty"
# Context: T33 — a JSONL empty string is real data, not a missing value.
def test_json_empty_string_is_not_missing(run, jsonl_file, schema_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": ""}])
    schema = schema_file([("id", "int"), ("v", "string")])
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--csv-null-literal", "NULL", "a.jsonl")
    assert column(res.stdout, "v") == [""]
