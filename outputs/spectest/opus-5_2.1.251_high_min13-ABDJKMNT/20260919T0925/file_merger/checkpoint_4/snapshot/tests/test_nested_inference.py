"""Without --schema: inference stays flat and nested inputs are rejected."""

import pyarrow as pa


# Spec: "Without --schema: Reject inputs containing nested objects/arrays in JSONL"
def test_jsonl_object_without_schema_is_error_6(run_cli, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.returncode == 6, result.stderr


# Spec: "Error: ERR 6 nested structure requires provided --schema (exit 6)"
def test_error_6_message(run_cli, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2]}])
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in result.stderr


# Spec: "Reject inputs containing nested objects/arrays in ... Parquet"
def test_parquet_struct_without_schema_is_error_6(run_cli, parquet_file):
    table = pa.table(
        {
            "id": pa.array([1], pa.int64()),
            "v": pa.array([{"a": 1}], pa.struct([pa.field("a", pa.int64())])),
        }
    )
    data = parquet_file("a.parquet", table)
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.returncode == 6, result.stderr


# Spec: "Inferred columns remain flat"
def test_inference_still_works_for_flat_inputs(run_cli, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 2, "v": "2024-03-04"}, {"id": 1, "v": "2024-03-05"}])
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.rows == [["id", "v"], ["1", "2024-03-05"], ["2", "2024-03-04"]]


# Spec: "CSV/TSV cells containing JSON treated as string"
def test_csv_json_cell_without_schema_is_a_string(run_cli, csv_file):
    data = csv_file("a.csv", 'id,v\n7,"{""a"": 1}"\n')
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.rows == [["id", "v"], ["7", '{"a": 1}']]


# Spec: "Without --schema, nested inputs not allowed (error 6)" — an empty object still counts
def test_empty_object_without_schema_is_error_6(run_cli, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {}}])
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.returncode == 6, result.stderr


# Spec: "Without --schema, nested inputs rejected (error 6)" — a schema lifts the ban
def test_schema_allows_the_same_input(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "json"}]})
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode == 0, result.stderr
