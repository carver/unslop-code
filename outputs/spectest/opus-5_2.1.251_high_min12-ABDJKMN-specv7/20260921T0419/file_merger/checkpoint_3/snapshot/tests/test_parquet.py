"""Spec section: Source Dialect Assumptions - Parquet."""
import datetime

import pytest

from conftest import body, header

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


# Phrase: "Parquet ... values come typed"
# Context: Source Dialect Assumptions / Casting.
def test_parquet_columns_and_values(run, work):
    work.parquet(
        "a.parquet",
        [{"id": 2, "name": "b"}, {"id": 1, "name": "a"}],
    )
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["1", "a"], ["2", "b"]]


def test_parquet_typed_columns_render_canonically(run, work):
    schema = pa.schema([
        ("id", pa.int64()),
        ("ratio", pa.float64()),
        ("flag", pa.bool_()),
        ("day", pa.date32()),
        ("ts", pa.timestamp("us")),
    ])
    work.parquet(
        "a.parquet",
        [{
            "id": 1,
            "ratio": 2.5,
            "flag": True,
            "day": datetime.date(2024, 7, 1),
            "ts": datetime.datetime(2024, 7, 1, 12, 0, 0),
        }],
        schema=schema,
    )
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.ok, r.stderr
    assert header(r) == ["day", "flag", "id", "ratio", "ts"]
    assert body(r) == [["2024-07-01", "true", "1", "2.5", "2024-07-01T12:00:00Z"]]


# Phrase: "If JSONL/Parquet value is `null` ... treat as missing -> emit null literal"
# Context: Casting.
def test_parquet_null_becomes_null_literal(run, work):
    work.parquet("a.parquet", [{"id": 1, "amount": None}, {"id": 2, "amount": 4.5}])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL",
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["amount", "id"]
    assert body(r) == [["NULL", "1"], ["4.5", "2"]]


# Phrase: "Parquet: flat schemas only (no nested/list/map types); nested fields trigger error 6"
# Context: Source Dialect Assumptions.
def test_parquet_list_column_is_error_6(run, work):
    work.parquet("a.parquet", [{"id": 1, "tags": ["x"]}])
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.returncode == 6
    assert r.stderr.strip()


def test_parquet_struct_column_is_error_6(run, work):
    work.parquet("a.parquet", [{"id": 1, "meta": {"k": "v"}}])
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.returncode == 6


def test_parquet_map_column_is_error_6(run, work):
    schema = pa.schema([
        ("id", pa.int64()),
        ("m", pa.map_(pa.string(), pa.int64())),
    ])
    work.parquet("a.parquet", [{"id": 1, "m": [("a", 1)]}], schema=schema)
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.returncode == 6


# Phrase: "Parquet reading must be streamed row group-wise"
# Context: New Input Types; many row groups must not change the result.
def test_parquet_multiple_row_groups(run, work):
    rows = [{"id": i} for i in range(500, 0, -1)]
    table = pa.Table.from_pylist(rows)
    path = work.path("a.parquet")
    pq.write_table(table, str(path), row_group_size=25)
    assert pq.ParquetFile(str(path)).num_row_groups > 1
    r = run("--output", "-", "--key", "id", path)
    assert r.ok, r.stderr
    assert [int(row[0]) for row in body(r)] == list(range(1, 501))


# Phrase: "If `--schema` provided, it defines exact output columns, types, and order"
# Context: Schema Resolution; a parquet int column re-cast to float/string.
def test_parquet_schema_recasts_values(run, work):
    work.schema("s.json", [("id", "string"), ("n", "float")])
    work.parquet("a.parquet", [{"id": 3, "n": 7}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["3", "7.0"]]


# Phrase: "Column set: union of all encountered field names"
# Context: Schema Resolution; a column missing from one parquet file is null there.
def test_parquet_union_of_columns(run, work):
    work.parquet("a.parquet", [{"id": 1, "a": "x"}])
    work.parquet("b.parquet", [{"id": 2, "b": "y"}])
    r = run(
        "--output", "-", "--key", "id", work.path("a.parquet"), work.path("b.parquet")
    )
    assert r.ok, r.stderr
    assert header(r) == ["a", "b", "id"]
    assert body(r) == [["x", "", "1"], ["", "y", "2"]]


# Phrase: "Type inference per `--infer` mode"
# Context: Schema Resolution; parquet carries its own declared types.
def test_parquet_declared_types_drive_inference(run, work):
    work.parquet("a.parquet", [{"id": 1, "n": 10}, {"id": 2, "n": 9}])
    r = run("--output", "-", "--key", "n", work.path("a.parquet"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["9", "10"]
