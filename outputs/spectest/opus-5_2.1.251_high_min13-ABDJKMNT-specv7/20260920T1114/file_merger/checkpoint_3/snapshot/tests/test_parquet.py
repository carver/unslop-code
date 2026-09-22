"""Spec section: Source Dialect Assumptions — Parquet inputs."""

import datetime

import pyarrow as pa
import pyarrow.parquet as pq

from conftest import column, header_of, rows_of


# Phrase: "Parquet: flat schemas only"
# Context: Source Dialect Assumptions. A flat file reads like any other input.
def test_parquet_flat_columns_are_read(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [2, 1], "note": ["bee", "ay"]})
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["1", "ay"], ["2", "bee"]]


# Phrase: "Parquet values come typed"
# Context: Casting. Booleans, floats and integers keep their declared types.
def test_parquet_typed_values_render_canonically(parquet_file, run_tool):
    parquet_file(
        "a.parquet",
        {"id": [1], "ok": [True], "amount": [2.5], "count": [7]},
    )
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert rows_of(result.stdout) == [["2.5", "7", "1", "true"]]


# Phrase: "Parquet values come typed"
# Context: Casting. Temporal columns normalise like their textual equivalents.
def test_parquet_temporal_values_normalise(parquet_file, run_tool):
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("day", pa.date32()),
            ("ts", pa.timestamp("us")),
        ]
    )
    parquet_file(
        "a.parquet",
        {
            "id": [1],
            "day": [datetime.date(2024, 7, 1)],
            "ts": [datetime.datetime(2024, 7, 1, 12, 0, 0)],
        },
        schema=schema,
    )
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "day") == ["2024-07-01"]
    assert column(result.stdout, "ts") == ["2024-07-01T12:00:00Z"]


# Phrase: "If JSONL/Parquet value is null ... treat as missing -> emit null literal"
# Context: Casting.
def test_parquet_null_becomes_the_null_literal(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "note": [None]})
    result = run_tool(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.parquet"
    )
    assert rows_of(result.stdout) == [["1", "NULL"]]


# Phrase: "flat schemas only (no nested/list/map types); nested fields trigger error 6"
# Context: Source Dialect Assumptions, Parquet. A struct column is rejected.
def test_parquet_struct_column_is_error_6(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "meta": [{"k": "v"}]})
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 6
    assert result.stderr


# Phrase: "no nested/list/map types"
# Context: Source Dialect Assumptions, Parquet. A list column is rejected.
def test_parquet_list_column_is_error_6(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "tags": [["x", "y"]]})
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 6
    assert result.stderr


# Phrase: "nested fields trigger error 6"
# Context: Source Dialect Assumptions. Ambiguity T32: the schema alone decides.
def test_parquet_empty_nested_column_is_still_error_6(run_tool, workdir):
    schema = pa.schema([("id", pa.int64()), ("tags", pa.list_(pa.string()))])
    pq.write_table(pa.table({"id": [], "tags": []}, schema=schema), workdir / "a.parquet")
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 6
    assert result.stderr


# Phrase: "Parquet reading must be streamed row group-wise"
# Context: New Input Types. Several row groups merge into one sorted result.
def test_parquet_with_many_row_groups_is_read_whole(run_tool, workdir):
    table = pa.table({"id": list(range(20, 0, -1))})
    pq.write_table(table, workdir / "a.parquet", row_group_size=3)
    result = run_tool(
        "--output", "-", "--key", "id", "--memory-limit-mb", "64", "a.parquet"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == [str(value) for value in range(1, 21)]


# Phrase: "For gzip, allow .gz suffix after base extension"
# Context: New Input Types. Gzip wraps binary formats too.
def test_gzipped_parquet_is_read(parquet_file, gzipped, run_tool):
    gzipped(parquet_file("a.parquet", {"id": [2, 1]}))
    result = run_tool("--output", "-", "--key", "id", "a.parquet.gz")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: "If --schema provided, it defines exact output columns, types, and order"
# Context: Schema Resolution. A Parquet column is cast to the declared type.
def test_parquet_values_are_cast_to_the_declared_schema(parquet_file, csv_file, run_tool):
    parquet_file("a.parquet", {"id": [1, 2], "amount": [3, 4]})
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"}, {"name": "amount", "type": "float"}]}',
    )
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.parquet")
    assert column(result.stdout, "amount") == ["3.0", "4.0"]
