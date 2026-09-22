"""The JSON Lines source dialect."""

import json

from conftest import rows_of


# Spec: "**JSONL**: one UTF-8 JSON object per line"
def test_each_line_is_one_record(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 2, "name": "bo"}, {"id": 1, "name": "al"}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout) == [["id", "name"], ["1", "al"], ["2", "bo"]]


# Spec: "**JSONL**: one UTF-8 JSON object per line"
def test_utf8_values_round_trip(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7, "name": "ünïcode"}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout)[1] == ["7", "ünïcode"]


# Spec: "**JSONL**: ... blank/whitespace lines ignored"
def test_blank_and_whitespace_lines_are_ignored(make_text, run):
    make_text("a.jsonl", '{"id": 1}\n\n   \n\t\n{"id": 2}\n')
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout) == [["id"], ["1"], ["2"]]


# Spec: "**JSONL**: ... keys case-sensitive"
def test_keys_differing_only_in_case_are_distinct_columns(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7, "Name": "x", "name": "y"}])
    rows = rows_of(run("--output", "-", "--key", "id", "a.jsonl").stdout)
    assert rows == [["Name", "id", "name"], ["x", "7", "y"]]


# Spec: "Column set: union of all encountered field names"
# Context: JSONL objects need not carry the same keys from line to line.
def test_keys_are_unioned_across_lines(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 1, "a": "x"}, {"id": 2, "b": "y"}])
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.jsonl")
    assert rows_of(proc.stdout) == [["a", "b", "id"], ["x", "NA", "1"], ["NA", "y", "2"]]


# Spec: "**JSONL**: ... `null` permitted" with
# "If JSONL/Parquet value is `null` ... treat as missing -> emit null literal"
def test_json_null_is_emitted_as_the_null_literal(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7, "v": None}])
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.jsonl")
    assert rows_of(proc.stdout)[1] == ["7", "NA"]


# Spec: "If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing"
# Context: see AMBIGUITIES T36 - an empty JSON string is a value, not a missing cell.
def test_empty_json_string_is_not_missing(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7, "v": ""}])
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.jsonl")
    assert rows_of(proc.stdout)[1] == ["7", ""]


# Spec: "JSONL values come typed (string/number/bool/null)"
# Context: a JSON bool is a bool column and renders as the bool literal.
def test_json_booleans_are_bools(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 1, "ok": True}, {"id": 2, "ok": False}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["1", "true"], ["2", "false"]]


# Spec: "For JSONL numbers, prefer `int` if integer and within range; otherwise `float`"
def test_integral_numbers_are_ints(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 10}, {"id": 9}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["9"], ["10"]]


# Spec: "For JSONL numbers, prefer `int` if integer and within range; otherwise `float`"
# Context: see AMBIGUITIES T31 - the test is on the value, so 5.0 is an int.
def test_integral_float_literal_is_treated_as_an_int(make_text, run):
    make_text("a.jsonl", '{"id": 5.0}\n{"id": 7}\n')
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["5"], ["7"]]


# Spec: "For JSONL numbers, prefer `int` ...; otherwise `float`"
def test_fractional_numbers_are_floats(make_jsonl, run):
    make_jsonl("a.jsonl", [{"v": 2.5}, {"v": 1.25}])
    proc = run("--output", "-", "--key", "v", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["1.25"], ["2.5"]]


# Spec: "prefer `int` if integer and within range; otherwise `float`"
# Context: an integral value beyond the 64 bit range is out of range for int.
def test_integral_number_out_of_int_range_is_a_float(make_text, run):
    make_text("a.jsonl", '{"v": 1e30}\n')
    proc = run("--output", "-", "--key", "v", "a.jsonl")
    assert rows_of(proc.stdout)[1] == ["1e+30"]


# Spec: "JSONL values come typed (string/number/bool/null)"
# Context: see AMBIGUITIES T32 - text in JSON is recognised like text in a CSV cell.
def test_json_strings_are_recognised_by_the_type_rules(make_jsonl, run):
    make_jsonl("a.jsonl", [{"ts": "2024-07-01T12:00:00+02:00"}, {"ts": "2024-07-01T09:00:00Z"}])
    proc = run("--output", "-", "--key", "ts", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["2024-07-01T09:00:00Z"], ["2024-07-01T10:00:00Z"]]


# Spec: "objects must be flat (no arrays/objects as values); ... nested structures trigger error 6"
def test_array_value_exits_6(make_text, run):
    make_text("a.jsonl", '{"id": 1, "tags": ["x"]}\n')
    proc = run("--output", "-", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 6
    assert proc.stderr.strip()


# Spec: "objects must be flat (no arrays/objects as values)"
def test_object_value_exits_6(make_text, run):
    make_text("a.jsonl", '{"id": 1, "meta": {"x": 1}}\n')
    proc = run("--output", "-", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 6


# Spec: "one UTF-8 JSON object per line"
# Context: see AMBIGUITIES T27 - a line that is not an object is a flatness violation.
def test_non_object_line_exits_6(make_text, run):
    make_text("a.jsonl", "[1, 2]\n")
    proc = run("--output", "-", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 6


# Spec: "one UTF-8 JSON object per line"
# Context: see AMBIGUITIES T27 - text that is not JSON at all is a malformed source.
def test_line_that_is_not_json_exits_5(make_text, run):
    make_text("a.jsonl", "{not json}\n")
    proc = run("--output", "-", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 5


# Spec: "All rows from all inputs appear exactly once; no deduplication"
# Context: identical JSONL objects are separate rows.
def test_identical_objects_are_kept(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7}, {"id": 7}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert rows_of(proc.stdout)[1:] == [["7"], ["7"]]


# Spec: "Extra input columns ignored; missing columns filled with null literal" (with --schema)
def test_provided_schema_selects_json_keys(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "extra": "drop", "v": "9"}])
    make_schema("s.json", [("id", "int"), ("v", "int"), ("missing", "string")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert rows_of(proc.stdout) == [["id", "v", "missing"], ["1", "9", ""]]


# Spec: "**JSONL**: one UTF-8 JSON object per line" under gzip
def test_gzipped_jsonl_is_read(make_jsonl, gzipped, run):
    gzipped(make_jsonl("a.jsonl", [{"id": 7}]))
    proc = run("--output", "-", "--key", "id", "a.jsonl.gz")
    assert rows_of(proc.stdout) == [["id"], ["7"]]


# Spec: "Avoid format-specific issues (e.g., don't load entire Parquet files or JSON arrays)"
# Context: the reader consumes line by line, so a large file needs no large buffer.
def test_large_jsonl_streams_under_a_small_memory_limit(make_text, run, workdir):
    body = "".join(json.dumps({"id": i, "pad": "x" * 200}) + "\n" for i in range(4000))
    make_text("a.jsonl", body)
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.jsonl")
    ids = [int(row[0]) for row in rows_of((workdir / "out.csv").read_text())[1:]]
    assert ids == sorted(range(4000))
