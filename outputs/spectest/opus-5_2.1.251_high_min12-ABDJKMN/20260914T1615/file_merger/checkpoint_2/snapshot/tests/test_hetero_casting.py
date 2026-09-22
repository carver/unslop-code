"""Spec section: Casting (heterogeneous sources)."""

from conftest import (body, col, header, pa, run, run_ok, write, write_jsonl,
                      write_parquet, write_schema, write_tsv)


# --- Spec: "CSV/TSV values are raw strings (after unescape for CSV)" ---
# Context: Casting; a quoted CSV field is unescaped before casting.
def test_csv_unescape_before_cast(ws):
    a = write(ws / "a.csv", 'id,v\n1,"12"\n')
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["12"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL int lands in a string column as canonical text.
def test_typed_int_into_string_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 42}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["42"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL bool into a string column uses the bool rendering.
def test_typed_bool_into_string_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": True}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["true"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL string of digits into an int column.
def test_typed_string_into_int_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "42"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["42"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL number into a float column.
def test_typed_int_into_float_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 3}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "float")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["3.0"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL ISO string into a timestamp column normalizes.
def test_typed_string_into_timestamp_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "ts": "2024-07-01T12:00:00+02:00"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("ts", "timestamp")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "ts") == ["2024-07-01T10:00:00Z"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a Parquet timestamp into a date column keeps the date part.
def test_parquet_timestamp_into_date_column(ws):
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("d", pyarrow.timestamp("us"))])
    a = write_parquet(ws / "a.parquet",
                      {"id": [1], "d": [dt.datetime(2024, 7, 1, 12)]},
                      schema=schema)
    s = write_schema(ws / "s.json", [("id", "int"), ("d", "date")])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    # A full timestamp is not an ISO date, so it fails the date cast and, under
    # the default coerce-null, becomes null.
    assert res.returncode == 0
    assert col(res.stdout, "d") == [""]


# --- Spec: "If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as
#            missing → emit null literal" ---
# Context: Casting; all three shapes of missingness in one run.
def test_all_missing_shapes_emit_null_literal(ws):
    a = write(ws / "a.csv", "id,v\n1,\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": None}])
    c = write_tsv(ws / "c.tsv", ["id", "v"], [["3", ""]])
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NULL",
                 a, b, c)
    assert col(res.stdout, "v") == ["NULL", "NULL", "NULL"]


# --- Spec: "On cast failure, follow `--on-type-error` from checkpoint 1" ---
# Context: Casting; coerce-null is the default.
def test_on_type_error_coerce_null_default(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "nope"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA"]


# --- Spec: "On cast failure, follow `--on-type-error`" ---
# Context: Casting; keep-string emits the original text.
def test_on_type_error_keep_string_on_jsonl(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "nope"}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "v") == ["nope"]


# --- Spec: "On cast failure, follow `--on-type-error`" ---
# Context: Casting; fail aborts, with a message on stderr.
def test_on_type_error_fail_on_parquet(ws):
    a = write_parquet(ws / "a.parquet", {"id": [1], "v": ["nope"]})
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# --- Spec: "For JSONL numbers, prefer `int` if integer and within range" ---
# Context: Casting; an integral JSON float satisfies an int column.
def test_jsonl_integral_float_satisfies_int_column(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "v": 7.0}\n')
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["7"]


# --- Spec: "prefer `int` if integer ...; otherwise `float`" ---
# Context: Casting; a fractional number cannot be an int (coerce-null default).
def test_jsonl_fractional_number_fails_int_column(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "v": 7.5}\n')
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA"]


# --- Spec: "Apply target output schema cast rules to every cell" ---
# Context: Casting; a JSONL number 1 into a bool column (checkpoint 1 accepts
# 1/0 as bool spellings, see T37).
def test_typed_one_into_bool_column(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 1}, {"id": 2, "v": 0}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "bool")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ["true", "false"]


# --- Spec: "If JSONL/Parquet value is `null` **or** CSV/TSV cell is empty" ---
# Context: Casting; an explicit JSONL empty string is a value, not missing (T38).
def test_jsonl_empty_string_is_not_missing(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": ""}])
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": None}])
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NULL", a, b)
    assert col(res.stdout, "v") == ["", "NULL"]


# --- Spec: "CSV/TSV values are raw strings" cast identically wherever they
#            came from ---
# Context: Casting; the same logical value from three formats renders alike.
def test_same_value_from_three_formats_renders_identically(ws):
    a = write(ws / "a.csv", "id,ts\n1,2024-07-01T12:00:00Z\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "ts": "2024-07-01T12:00:00Z"}])
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("ts", pyarrow.timestamp("us"))])
    c = write_parquet(ws / "c.parquet",
                      {"id": [3], "ts": [dt.datetime(2024, 7, 1, 12)]},
                      schema=schema)
    s = write_schema(ws / "s.json", [("id", "int"), ("ts", "timestamp")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a, b, c)
    assert col(res.stdout, "ts") == ["2024-07-01T12:00:00Z"] * 3
