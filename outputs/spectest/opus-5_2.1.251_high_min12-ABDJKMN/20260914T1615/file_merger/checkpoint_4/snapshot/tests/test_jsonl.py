"""Spec section: Source Dialect Assumptions — JSON Lines (NDJSON)."""

from conftest import (body, col, header, rows_of, run, run_ok, write,
                      write_jsonl, write_schema)


# --- Spec: "JSONL: one UTF-8 JSON object per line" ---
# Context: Source Dialect Assumptions; each line is one record.
def test_jsonl_one_object_per_line(ws):
    a = write_jsonl(ws / "a.jsonl",
                    [{"id": 2, "n": "b"}, {"id": 1, "n": "a"}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "one UTF-8 JSON object per line" ---
# Context: Source Dialect Assumptions; non-ASCII text round-trips.
def test_jsonl_utf8_values(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "n": "héllo→"}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "n") == ["héllo→"]


# --- Spec: "objects must be flat (no arrays/objects as values)" ---
# Context: Source Dialect Assumptions; a list value is error 6.
def test_jsonl_array_value_is_error_6(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "tags": ["x", "y"]}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6
    assert res.stderr.strip() != ""


# --- Spec: "objects must be flat (no arrays/objects as values)" ---
# Context: Source Dialect Assumptions; a nested object value is error 6.
def test_jsonl_object_value_is_error_6(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "meta": {"k": "v"}}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "objects must be flat" — even an empty container ---
# Context: Source Dialect Assumptions.
def test_jsonl_empty_array_value_is_error_6(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "tags": []}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "one UTF-8 JSON **object** per line" ---
# Context: Source Dialect Assumptions; a top-level array violates the structure
# rule (see T30).
def test_jsonl_top_level_array_line_is_error_6(ws):
    a = write(ws / "a.jsonl", "[1, 2]\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "one UTF-8 JSON object per line" with broken syntax ---
# Context: Source Dialect Assumptions; malformed data, not a structure problem.
def test_jsonl_invalid_json_is_error_5(ws):
    a = write(ws / "a.jsonl", '{"id": 1,\n')
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 5


# --- Spec: "`null` permitted" ---
# Context: Source Dialect Assumptions; null becomes the null literal.
def test_jsonl_null_is_permitted_and_emits_null_literal(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": None}])
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA"]


# --- Spec: "keys case-sensitive" ---
# Context: Source Dialect Assumptions; `a` and `A` are distinct columns.
def test_jsonl_keys_are_case_sensitive(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "low", "V": "up"}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["V", "id", "v"]
    assert body(res.stdout) == ["up,1,low"]


# --- Spec: "blank/whitespace lines ignored" ---
# Context: Source Dialect Assumptions.
def test_jsonl_blank_and_whitespace_lines_ignored(ws):
    a = write(ws / "a.jsonl",
              '\n{"id": 2}\n   \n\t\n{"id": 1}\n\n')
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "Column set: union of all encountered field names" ---
# Context: Schema Resolution; JSONL objects may have differing key sets.
def test_jsonl_ragged_objects_union_their_keys(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "x": "p"}, {"id": 2, "y": "q"}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "x", "y"]
    assert body(res.stdout) == ["1,p,", "2,,q"]


# --- Spec: "JSONL values come typed (string/number/bool/null)" ---
# Context: Casting; booleans render with the checkpoint-1 bool rendering.
def test_jsonl_bool_values(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "ok": True}, {"id": 2, "ok": False}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "ok") == ["true", "false"]


# --- Spec: "For JSONL numbers, prefer `int` if integer and within range" ---
# Context: Casting.
def test_jsonl_integral_number_prefers_int(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "n": 5}\n{"id": 2, "n": 7.0}\n')
    s = write_schema(ws / "s.json", [("id", "int"), ("n", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "n") == ["5", "7"]


# --- Spec: "prefer `int` if integer and within range; otherwise `float`" ---
# Context: Casting; a fractional number stays float.
def test_jsonl_fractional_number_is_float(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "n": 2.5}\n')
    s = write_schema(ws / "s.json", [("id", "int"), ("n", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "n") == ["2.5"]


# --- Spec: "prefer `int` if integer and **within range**; otherwise `float`" ---
# Context: Casting; an integer beyond 64-bit range falls back to float (T36).
def test_jsonl_out_of_range_integer_becomes_float(ws):
    huge = 2 ** 70
    a = write(ws / "a.jsonl", '{"id": 1, "n": %d}\n' % huge)
    s = write_schema(ws / "s.json", [("id", "int"), ("n", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "n") == [repr(float(huge))]


# --- Spec: "If JSONL/Parquet value is `null` ... treat as missing" ---
# Context: Casting; a key absent from the object is also missing.
def test_jsonl_absent_key_is_missing(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}, {"id": 2, "v": "x"}])
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA", "x"]


# --- Spec: "JSONL values come typed" — strings stay strings on output ---
# Context: Casting; a JSON string in a string column is emitted verbatim.
def test_jsonl_string_value_passes_through(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "007"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["007"]


# --- Spec: "blank/whitespace lines ignored" — an entirely empty file ---
# Context: Source Dialect Assumptions; contributes nothing.
def test_empty_jsonl_file_contributes_nothing(ws):
    a = write(ws / "a.jsonl", "")
    b = write(ws / "b.csv", "id\n7\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert header(res.stdout) == ["id"]
    assert body(res.stdout) == ["7"]


# --- Spec: JSONL is one of the accepted input types ---
# Context: New Input Types; JSONL merges with CSV under one schema.
def test_jsonl_and_csv_merge(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 3, "v": "c"}])
    b = write(ws / "b.csv", "id,v\n1,a\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert body(res.stdout) == ["1,a", "3,c"]


# --- Spec: "keys case-sensitive" / duplicate keys in one object ---
# Context: Source Dialect Assumptions; last value wins (see T45).
def test_jsonl_duplicate_key_last_wins(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "v": "first", "v": "second"}\n')
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "v") == ["second"]
