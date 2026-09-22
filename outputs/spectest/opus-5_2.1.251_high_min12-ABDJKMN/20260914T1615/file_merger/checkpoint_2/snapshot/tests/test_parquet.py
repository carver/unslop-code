"""Spec section: Source Dialect Assumptions — Parquet."""

import pytest

from conftest import (body, col, header, pa, run, run_ok, write, write_parquet,
                      write_schema)


# --- Spec: "Parquet: flat schemas only" ---
# Context: Source Dialect Assumptions; a flat file reads normally.
def test_parquet_flat_file_reads(ws):
    a = write_parquet(ws / "a.parquet", {"id": [2, 1], "v": ["b", "a"]})
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "v"]
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "Parquet values come typed" ---
# Context: Casting; int64 columns are ints, doubles are floats.
def test_parquet_numeric_types(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("amt", pyarrow.float64())])
    a = write_parquet(ws / "a.parquet", {"id": [2, 10], "amt": [1.5, 3.0]},
                      schema=schema)
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "id") == ["2", "10"]
    assert col(res.stdout, "amt") == ["1.5", "3.0"]


# --- Spec: "Parquet values come typed" ---
# Context: Casting; a boolean column renders with the canonical bool spelling.
def test_parquet_bool_type(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("ok", pyarrow.bool_())])
    a = write_parquet(ws / "a.parquet", {"id": [1, 2], "ok": [True, False]},
                      schema=schema)
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "ok") == ["true", "false"]


# --- Spec: "Parquet values come typed" ---
# Context: Casting; timestamps normalize to UTC with a Z suffix.
def test_parquet_timestamp_type(ws):
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("ts", pyarrow.timestamp("us"))])
    a = write_parquet(
        ws / "a.parquet",
        {"id": [1], "ts": [dt.datetime(2024, 7, 1, 12, 0, 0)]}, schema=schema)
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "ts") == ["2024-07-01T12:00:00Z"]


# --- Spec: "Parquet values come typed" with a zoned timestamp ---
# Context: Casting; a non-UTC zone is converted to UTC.
def test_parquet_zoned_timestamp_converts_to_utc(ws):
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("ts", pyarrow.timestamp("us", tz="+02:00"))])
    a = write_parquet(
        ws / "a.parquet",
        {"id": [1], "ts": [dt.datetime(2024, 7, 1, 12, 0, 0,
                                       tzinfo=dt.timezone.utc)]},
        schema=schema)
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "ts") == ["2024-07-01T12:00:00Z"]


# --- Spec: "Parquet values come typed" ---
# Context: Casting; a date32 column renders as an ISO date.
def test_parquet_date_type(ws):
    import datetime as dt
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("d", pyarrow.date32())])
    a = write_parquet(ws / "a.parquet",
                      {"id": [1], "d": [dt.date(2024, 7, 1)]}, schema=schema)
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "d") == ["2024-07-01"]


# --- Spec: "If JSONL/Parquet value is `null` ... treat as missing" ---
# Context: Casting.
def test_parquet_null_is_missing(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("v", pyarrow.string())])
    a = write_parquet(ws / "a.parquet", {"id": [1], "v": [None]}, schema=schema)
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA"]


# --- Spec: "flat schemas only (no nested/list/map types); nested fields
#            trigger error 6" ---
# Context: Source Dialect Assumptions; a list column.
def test_parquet_list_column_is_error_6(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("tags", pyarrow.list_(pyarrow.string()))])
    a = write_parquet(ws / "a.parquet", {"id": [1], "tags": [["x", "y"]]},
                      schema=schema)
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6
    assert res.stderr.strip() != ""


# --- Spec: "nested fields trigger error 6" ---
# Context: Source Dialect Assumptions; a struct column.
def test_parquet_struct_column_is_error_6(ws):
    pyarrow = pa()
    schema = pyarrow.schema([
        ("id", pyarrow.int64()),
        ("meta", pyarrow.struct([("k", pyarrow.string())])),
    ])
    a = write_parquet(ws / "a.parquet", {"id": [1], "meta": [{"k": "v"}]},
                      schema=schema)
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "no nested/list/map types" ---
# Context: Source Dialect Assumptions; a map column.
def test_parquet_map_column_is_error_6(ws):
    pyarrow = pa()
    schema = pyarrow.schema([
        ("id", pyarrow.int64()),
        ("m", pyarrow.map_(pyarrow.string(), pyarrow.string())),
    ])
    a = write_parquet(ws / "a.parquet", {"id": [1], "m": [[("k", "v")]]},
                      schema=schema)
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "Parquet reading must be streamed row group-wise" ---
# Context: New Input Types; many small row groups all contribute their rows.
def test_parquet_multiple_row_groups_all_rows(ws):
    n = 5000
    a = write_parquet(ws / "a.parquet",
                      {"id": list(range(n - 1, -1, -1))}, row_group_size=250)
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "64", a)
    ids = [int(v) for v in col(res.stdout, "id")]
    assert ids == list(range(n))


# --- Spec: "`--parquet-row-group-bytes` is advisory for batch sizing" ---
# Context: New Input Types; a small advisory value does not change the output.
def test_parquet_row_group_bytes_is_advisory(ws):
    n = 2000
    a = write_parquet(ws / "a.parquet",
                      {"id": list(range(n)), "v": ["x" * 20] * n},
                      row_group_size=100)
    small = run_ok("--output", "-", "--key", "id",
                   "--parquet-row-group-bytes", "1024", a)
    big = run_ok("--output", "-", "--key", "id",
                 "--parquet-row-group-bytes", "104857600", a)
    assert small.stdout == big.stdout


# --- Spec: "Column set: union of all encountered field names" ---
# Context: Schema Resolution; a Parquet schema with no rows still contributes
# its columns (see T43).
def test_parquet_zero_rows_contributes_columns(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()), ("z", pyarrow.string())])
    a = write_parquet(ws / "a.parquet", {"id": [], "z": []}, schema=schema)
    b = write(ws / "b.csv", "id\n1\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert header(res.stdout) == ["id", "z"]
    assert body(res.stdout) == ["1,"]


# --- Spec: Parquet is one of the accepted input types ---
# Context: New Input Types; merges with CSV and JSONL in one run.
def test_parquet_merges_with_other_formats(ws):
    from conftest import write_jsonl
    a = write_parquet(ws / "a.parquet", {"id": [3], "v": ["c"]})
    b = write_jsonl(ws / "b.jsonl", [{"id": 2, "v": "b"}])
    c = write(ws / "c.csv", "id,v\n1,a\n")
    res = run_ok("--output", "-", "--key", "id", a, b, c)
    assert body(res.stdout) == ["1,a", "2,b", "3,c"]


# --- Spec: "Extra input columns ignored" with an explicit schema ---
# Context: Schema Resolution; only the schema's Parquet columns are read.
def test_parquet_extra_columns_ignored_under_schema(ws):
    a = write_parquet(ws / "a.parquet",
                      {"id": [1], "keep": ["k"], "drop": ["d"]})
    s = write_schema(ws / "s.json", [("id", "int"), ("keep", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id", "keep"]
    assert body(res.stdout) == ["1,k"]
