"""`Casting` across heterogeneous sources."""
from conftest import (merge_paths, pa_modules, write, write_jsonl,
                      write_parquet, write_schema)


# --- Spec: "CSV/TSV values are raw strings (after unescape for CSV)" ------
def test_csv_values_are_unescaped_before_casting(tmp_path):
    a = write(tmp_path, "a.csv", 'id,v\n7,"a""b"\n')
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ['7', 'a"b']


def test_csv_quoted_number_still_casts(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write(tmp_path, "a.csv", 'id,v\n1,"42"\n')
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "42"]


# --- Spec: "JSONL values come typed (string/number/bool/null)" ------------
def test_jsonl_bool_into_string_column(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": True}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "true"]


def test_jsonl_string_value_casts_like_text(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": "007"}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "7"]


def test_jsonl_bool_is_inferred_as_bool(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "v": True}, {"id": 2, "v": False}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["true", "false"]


# --- Spec: "Apply target output schema cast rules to every cell" ----------
def test_number_casts_into_declared_float_column(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "float")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": 7}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "7.0"]


def test_typed_string_casts_into_declared_timestamp_column(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("id", "int"), ("ts", "timestamp")])
    a = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "ts": "2024-07-01T12:00:00+02:00"}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "2024-07-01T10:00:00Z"]


# --- Spec: "For JSONL numbers, prefer `int` if integer and within range;
#            otherwise `float`" --------------------------------------------
def test_jsonl_integral_number_prefers_int(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    a = write(tmp_path, "a.jsonl", '{"id": 1, "v": 5}\n{"id": 2, "v": 5.0}\n')
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["5", "5"]


def test_jsonl_non_integral_number_is_float(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    a = write(tmp_path, "a.jsonl", '{"id": 1, "v": 2.5}\n')
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "2.5"]


def test_jsonl_out_of_int64_range_number_is_float(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    a = write(tmp_path, "a.jsonl", '{"id": 1, "v": 99999999999999999999}\n')
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1][1] == "1e+20"


# --- Spec: "If JSONL/Parquet value is `null` or CSV/TSV cell is empty,
#            treat as missing -> emit null literal" ------------------------
def test_null_and_empty_all_render_as_null_literal(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n1,\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": None}])
    p = write_parquet(tmp_path, "c.parquet", [{"id": 3, "v": None}])
    r = merge_paths([c, j, p], "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["NULL", "NULL", "NULL"]


def test_missing_key_in_jsonl_object_is_null(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": "x"}, {"id": 2}])
    r = merge_paths([a], "--key", "id", "--csv-null-literal", "NA")
    assert r.ok, r
    assert r.rows()[2] == ["2", "NA"]


# --- Spec: "On cast failure, follow --on-type-error from checkpoint 1" ----
def test_cast_failure_coerce_null_is_the_default(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": 2.5}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", ""]


def test_cast_failure_keep_string_keeps_original_text(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": 2.5}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "keep-string")
    assert r.ok, r
    assert r.rows()[1] == ["1", "2.5"]


def test_cast_failure_fail_exits_with_the_cast_error_code(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": "abc"}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert r.stderr.strip()


# --- Spec: "Parquet values come typed" - a typed int column into a
#            declared string column ---------------------------------------
def test_parquet_int_into_string_column(tmp_path):
    pa, _ = pa_modules()
    schema_arrow = pa.schema([("id", pa.int64()), ("v", pa.int32())])
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    a = write_parquet(tmp_path, "a.parquet", [{"id": 1, "v": 42}],
                      schema=schema_arrow)
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "42"]


# --- Spec: cast rules are shared, so a typed bool does not become an int --
def test_typed_bool_into_int_column_is_a_cast_failure(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": True}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", ""]
