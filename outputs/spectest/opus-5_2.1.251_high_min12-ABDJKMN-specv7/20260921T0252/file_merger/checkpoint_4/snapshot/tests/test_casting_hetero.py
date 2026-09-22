"""Checkpoint 2 - Casting values coming from typed and untyped sources."""
import datetime
import json

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_csv,
                      write_file, write_jsonl, write_parquet, write_schema,
                      write_tsv, body, col)

if HAVE_PARQUET:
    import pyarrow as pa


# --------------------------------------------------------------------------
# Phrase: "CSV/TSV values are raw strings (after unescape for CSV)"
# Context: Casting.
# --------------------------------------------------------------------------
def test_csv_values_are_unescaped_before_casting(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_csv(tmp_path / "a.csv", ['id,v', '1,"say ""hi"""'])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ['say "hi"']


def test_tsv_values_are_raw_strings(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "int")])
    a = write_tsv(tmp_path / "a.tsv", ["id\tv", "1\t42"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["42"]


def test_tsv_backslash_is_not_an_escape(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_tsv(tmp_path / "a.tsv", ["id\tv", "1\tC:\\path"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["C:\\path"]


# --------------------------------------------------------------------------
# Phrase: "JSONL values come typed (string/number/bool/null)"
# Context: Casting.
# --------------------------------------------------------------------------
def test_jsonl_bool_renders_as_bool(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "b": True}, {"id": 2, "b": False}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == ["true", "false"]


def test_jsonl_bool_to_string_schema(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("b", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "b": True}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == ["true"]


def test_jsonl_string_value_is_inferred_like_csv_text(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": "0012"}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    # "0012" parses as int under the checkpoint-1 casting rules.
    assert col(res.rows(), "v") == ["12"]


def test_jsonl_string_holding_a_timestamp_normalises(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "t": "2024-07-01T12:00:00+02:00"}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["2024-07-01T10:00:00Z"]


# --------------------------------------------------------------------------
# Phrase: "For JSONL numbers, prefer int if integer and within range;
#          otherwise float"
# Context: Casting.
# --------------------------------------------------------------------------
def test_jsonl_integral_float_becomes_int(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": 5.0}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["5"]


def test_jsonl_integral_float_infers_as_int(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "n": 5.0}, {"id": 2, "n": 7.0}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["5", "7"]


def test_jsonl_non_integral_number_is_float(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": 2.5}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["2.5"]


def test_jsonl_out_of_int_range_number_is_float(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "float")])
    a = write_file(tmp_path / "a.jsonl",
                   '{"id": 1, "n": 123456789012345678901234567890}\n')
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    got = col(res.rows(), "n")[0]
    assert float(got) == 1.2345678901234568e+29
    assert got != "123456789012345678901234567890"


def test_jsonl_int_within_range_keeps_exact_digits(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    a = write_file(tmp_path / "a.jsonl",
                   '{"id": 1, "n": 9007199254740993}\n')
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["9007199254740993"]


# --------------------------------------------------------------------------
# Phrase: "Parquet values come typed"
# Context: Casting.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_int_column(tmp_path):
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "n": [42]})
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["42"]


@needs_parquet
def test_parquet_float_column(tmp_path):
    schema = pa.schema([("id", pa.int64()), ("n", pa.float64())])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "n": [2.5]},
                        schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["2.5"]


@needs_parquet
def test_parquet_bool_column(tmp_path):
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1, 2], "b": [True, False]})
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == ["true", "false"]


@needs_parquet
def test_parquet_date_column(tmp_path):
    schema = pa.schema([("id", pa.int64()), ("d", pa.date32())])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "d": [datetime.date(2024, 7, 1)]},
                        schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "d") == ["2024-07-01"]


@needs_parquet
def test_parquet_timestamp_column_normalised_to_utc(tmp_path):
    schema = pa.schema([("id", pa.int64()),
                        ("t", pa.timestamp("us", tz="UTC"))])
    value = datetime.datetime(2024, 7, 1, 12, 0, 0,
                              tzinfo=datetime.timezone.utc)
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "t": [value]},
                        schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["2024-07-01T12:00:00Z"]


@needs_parquet
def test_parquet_naive_timestamp_treated_as_utc(tmp_path):
    schema = pa.schema([("id", pa.int64()), ("t", pa.timestamp("us"))])
    value = datetime.datetime(2024, 7, 1, 12, 0, 0)
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "t": [value]},
                        schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["2024-07-01T12:00:00Z"]


@needs_parquet
def test_parquet_int32_is_int(tmp_path):
    schema = pa.schema([("id", pa.int32()), ("n", pa.int32())])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "n": [7]},
                        schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["7"]


# --------------------------------------------------------------------------
# Phrase: "Apply target output schema cast rules to every cell"
# Context: Casting; the checkpoint-1 rules apply to typed sources too.
# --------------------------------------------------------------------------
def test_jsonl_number_cast_to_declared_float(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "float")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": 3}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["3.0"]


def test_jsonl_string_cast_to_declared_bool(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("b", "bool")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "b": "true"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == ["true"]


@needs_parquet
def test_parquet_int_cast_to_declared_timestamp_fails(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("t", "timestamp")])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "t": [5]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == [""]


# --------------------------------------------------------------------------
# Phrase: "If JSONL/Parquet value is null or CSV/TSV cell is empty, treat as
#          missing -> emit null literal"
# Context: Casting.
# --------------------------------------------------------------------------
def test_jsonl_null_emits_null_literal(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["NULL"]


def test_jsonl_absent_key_emits_null_literal(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["NULL"]


@needs_parquet
def test_parquet_null_emits_null_literal(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "int")])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "v": [None]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["NULL"]


def test_empty_tsv_cell_is_missing(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_tsv(tmp_path / "a.tsv", ["id\tv", "1\t"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["NULL"]


def test_jsonl_empty_string_is_not_missing(tmp_path):
    # The spec lists "JSONL/Parquet value is null" and "CSV/TSV cell is
    # empty" as the two missing cases; an empty JSON string is neither.
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": ""}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == [""]


def test_parquet_empty_string_is_not_missing(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": ""}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "-", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == [""]


# --------------------------------------------------------------------------
# Phrase: "On cast failure, follow --on-type-error from checkpoint 1"
# Context: Casting.
# --------------------------------------------------------------------------
def test_on_type_error_coerce_null_for_jsonl(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": "abc"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "coerce-null", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == [""]


def test_on_type_error_keep_string_for_jsonl(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": "abc"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["abc"]


def test_on_type_error_fail_for_jsonl(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "n": "abc"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", a)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


@needs_parquet
def test_on_type_error_keep_string_for_parquet(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "n": [2.5]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["2.5"]
