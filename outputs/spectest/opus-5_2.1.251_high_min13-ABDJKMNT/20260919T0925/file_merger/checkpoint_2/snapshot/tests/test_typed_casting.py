"""Casting cells from typed (JSONL/Parquet) and raw-text (CSV/TSV) sources."""

import datetime as dt
import json

import pytest


@pytest.fixture
def schema_file(tmp_path):
    def _write(columns, name="schema.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    return _write


def test_csv_values_are_raw_strings_after_unescape(run_cli, csv_file, schema_file):
    # Spec: "CSV/TSV values are raw strings (after unescape for CSV)"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "note", "type": "string"}])
    a = csv_file("a.csv", 'id,note\n1,"a""b"\n')
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "note"], ["1", 'a"b']]


def test_jsonl_values_come_typed(run_cli, jsonl_file, schema_file):
    # Spec: "JSONL values come typed (string/number/bool/null)"
    schema = schema_file(
        [
            {"name": "id", "type": "int"},
            {"name": "flag", "type": "bool"},
            {"name": "ratio", "type": "float"},
            {"name": "text", "type": "string"},
        ]
    )
    a = jsonl_file("a.jsonl", [{"id": 1, "flag": True, "ratio": 0.5, "text": "x"}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "flag", "ratio", "text"], ["1", "True", "0.5", "x"]]


def test_parquet_values_come_typed(run_cli, parquet_file, schema_file):
    # Spec: "Parquet values come typed"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "ts", "type": "timestamp"}])
    a = parquet_file("a.parquet", {"id": [1], "ts": [dt.datetime(2024, 7, 1, 12, 30)]})
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "ts"], ["1", "2024-07-01T12:30:00Z"]]


def test_target_schema_cast_applied_to_every_cell(run_cli, csv_file, jsonl_file, schema_file):
    # Spec: "Apply target output schema cast rules to every cell"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "amount", "type": "float"}])
    a = csv_file("a.csv", "id,amount\n1,3\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "amount": 4}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a, b)
    assert result.rows == [["id", "amount"], ["1", "3.0"], ["2", "4.0"]]


def test_jsonl_integral_number_prefers_int(run_cli, jsonl_file):
    # Spec: "For JSONL numbers, prefer `int` if integer and within range; otherwise `float`"
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 5.0}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "n"], ["1", "5"]]


def test_jsonl_fractional_number_is_float(run_cli, jsonl_file):
    # Spec: "prefer `int` if integer and within range; otherwise `float`"
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 5.25}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.rows == [["id", "n"], ["1", "5.25"]]


def test_jsonl_out_of_range_integer_is_float(run_cli, text_file):
    # Spec: "prefer `int` if integer and within range; otherwise `float`" (AMBIGUITIES T27: int64 range)
    a = text_file("a.jsonl", '{"id": 1, "n": 92233720368547758080}\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "n"], ["1", "9.223372036854776e+19"]]


def test_jsonl_null_and_empty_csv_cell_are_both_missing(run_cli, csv_file, jsonl_file):
    # Spec: "If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal"
    a = csv_file("a.csv", "id,note\n1,\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "note": None}])
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NULL", a, b)
    assert result.rows == [["id", "note"], ["1", "NULL"], ["2", "NULL"]]


def test_bool_casts_to_int_column(run_cli, jsonl_file, schema_file):
    # Spec: "Apply target output schema cast rules to every cell" (AMBIGUITIES T28)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "flag", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "flag": True}, {"id": 2, "flag": False}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "flag"], ["1", "1"], ["2", "0"]]


def test_number_casts_to_bool_column_for_zero_and_one(run_cli, jsonl_file, schema_file):
    # Spec: cast rules, with checkpoint 1's "`bool` includes `1`/`0`" (AMBIGUITIES T28)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "flag", "type": "bool"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "flag": 1}, {"id": 2, "flag": 0}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "flag"], ["1", "True"], ["2", "False"]]


def test_typed_value_casts_to_string_column(run_cli, jsonl_file, schema_file):
    # Spec: "Apply target output schema cast rules to every cell"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "n", "type": "string"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 7}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "n"], ["1", "7"]]


def test_parquet_date_widens_into_timestamp_column(run_cli, parquet_file, schema_file):
    # Spec: cast rules; checkpoint 1 widens a date-only source to midnight UTC (AMBIGUITIES T4, T28)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "d", "type": "timestamp"}])
    a = parquet_file("a.parquet", {"id": [1], "d": [dt.date(2024, 7, 1)]})
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id", "d"], ["1", "2024-07-01T00:00:00Z"]]


def test_timestamp_into_date_column_is_a_cast_failure(run_cli, parquet_file, schema_file):
    # Spec: "On cast failure, follow `--on-type-error`" (AMBIGUITIES T28)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "ts", "type": "date"}])
    a = parquet_file("a.parquet", {"id": [1], "ts": [dt.datetime(2024, 7, 1, 12, 0)]})
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "ts"], ["1", "NA"]]


def test_typed_cast_failure_coerces_to_null_by_default(run_cli, jsonl_file, schema_file):
    # Spec: "On cast failure, follow `--on-type-error` from checkpoint 1" (`coerce-null` default)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "n", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 2.5}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "n"], ["1", "NA"]]


def test_typed_cast_failure_keeps_string(run_cli, jsonl_file, schema_file):
    # Spec: "follow `--on-type-error`" — `keep-string` emits the original value as text
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "n", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 2.5}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", a)
    assert result.rows == [["id", "n"], ["1", "2.5"]]


def test_typed_cast_failure_can_fail_the_run(run_cli, jsonl_file, schema_file):
    # Spec: "follow `--on-type-error`" — `fail` reports the offending cell and exits non-zero
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "n", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 2.5}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", a)
    assert result.returncode == 4
    assert "a.jsonl" in result.stderr and "n" in result.stderr
