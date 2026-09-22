"""Spec section: Source Dialect Assumptions - JSONL."""
import json

from conftest import body, header


# Phrase: "JSONL: one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions.
def test_jsonl_object_per_line(run, work):
    work.jsonl("a.jsonl", [{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["1", "a"], ["2", "b"]]


def test_jsonl_utf8_values_round_trip(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "name": "café 中"}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "café 中"]]


# Phrase: "blank/whitespace lines ignored"
# Context: Source Dialect Assumptions - JSONL.
def test_jsonl_blank_and_whitespace_lines_ignored(run, work):
    work.write(
        "a.jsonl",
        '\n{"id": 2}\n   \n\t\n{"id": 1}\n\n',
    )
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"]]


# Phrase: "keys case-sensitive"
# Context: Source Dialect Assumptions - JSONL; `id` and `ID` are distinct columns.
def test_jsonl_keys_are_case_sensitive(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "ID": 9}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert header(r) == ["ID", "id"]
    assert body(r) == [["9", "1"]]


# Phrase: "`null` permitted"
# Context: Source Dialect Assumptions - JSONL; and "If JSONL value is null ... emit null literal".
def test_jsonl_null_becomes_null_literal(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "amount": None}])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL",
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["amount", "id"]
    assert body(r) == [["NULL", "1"]]


def test_jsonl_null_does_not_break_inference(run, work):
    work.jsonl("a.jsonl", [{"id": 2, "n": None}, {"id": 1, "n": 5}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "5"], ["2", ""]]


# Phrase: "objects must be flat (no arrays/objects as values)"
# Context: Source Dialect Assumptions - JSONL; "nested structures trigger error 6".
def test_jsonl_array_value_is_error_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "tags": ["x", "y"]}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6
    assert r.stderr.strip()


def test_jsonl_object_value_is_error_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "meta": {"k": "v"}}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6


def test_jsonl_empty_array_value_is_error_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "tags": []}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6


# Phrase: "one UTF-8 JSON object per line"
# Context: malformed lines and non-object lines are input errors, not nesting errors.
def test_jsonl_malformed_line_is_error_5(run, work):
    work.write("a.jsonl", '{"id": 1}\n{not json}\n')
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 5


def test_jsonl_top_level_non_object_is_error_5(run, work):
    work.write("a.jsonl", '{"id": 1}\n[1, 2]\n')
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 5


# Phrase: "Column set: union of all encountered field names"
# Context: Schema Resolution; JSONL objects may have different key sets.
def test_jsonl_column_set_is_union_of_keys(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "a": "x"}, {"id": 2, "b": "y"}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert header(r) == ["a", "b", "id"]
    assert body(r) == [["x", "", "1"], ["", "y", "2"]]


# Phrase: "JSONL values come typed (string/number/bool/null)"
# Context: Casting.
def test_jsonl_bool_values_are_typed(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "flag": True}, {"id": 2, "flag": False}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert header(r) == ["flag", "id"]
    assert body(r) == [["true", "1"], ["false", "2"]]


def test_jsonl_string_values_stay_strings(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "note": "hello, world"}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "hello, world"]]


# Phrase: "For JSONL numbers, prefer `int` if integer and within range; otherwise `float`"
# Context: Casting.
def test_jsonl_integral_number_renders_as_int(run, work):
    work.write("a.jsonl", '{"id": 1, "n": 2.0}\n')
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "2"]]


def test_jsonl_fractional_number_renders_as_float(run, work):
    work.write("a.jsonl", '{"id": 1, "n": 2.5}\n')
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "2.5"]]


def test_jsonl_out_of_int_range_number_stays_float(run, work):
    work.write("a.jsonl", '{"id": 1, "n": 1e30}\n')
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r)[0][1] == str(1e30)


# Phrase: "If `--schema` provided, it defines exact output columns, types, and order.
#          Extra input columns ignored; missing columns filled with null literal"
# Context: Schema Resolution; applied to a JSONL source.
def test_jsonl_schema_selects_and_casts(run, work):
    work.schema("s.json", [("id", "int"), ("amount", "float")])
    work.jsonl("a.jsonl", [{"id": "7", "amount": 3, "extra": "drop me"}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "amount"]
    assert body(r) == [["7", "3.0"]]


# Phrase: "Sorting by `--key` uses casted key values"
# Context: Sorting and Stability; JSONL numbers sort numerically.
def test_jsonl_numeric_key_sorts_numerically(run, work):
    work.jsonl("a.jsonl", [{"id": 10}, {"id": 9}, {"id": 100}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["9"], ["10"], ["100"]]
