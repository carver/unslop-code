"""The Parquet source."""

import datetime

import pyarrow as pa

from conftest import column, rows_of


# Spec: "Accepted file types: ... Parquet" with "Parquet values come typed"
def test_columns_keep_their_declared_types(make_parquet, run):
    make_parquet(
        "a.parquet",
        {
            "i": pa.array([2, 1], pa.int64()),
            "f": pa.array([1.5, 2.0], pa.float64()),
            "b": pa.array([True, False]),
            "s": pa.array(["x", "y"]),
        },
    )
    proc = run("--output", "-", "--key", "i", "a.parquet")
    assert rows_of(proc.stdout) == [["b", "f", "i", "s"], ["false", "2.0", "1", "y"], ["true", "1.5", "2", "x"]]


# Spec: "Parquet values come typed" with "date stays `YYYY-MM-DD`"
def test_date_columns_are_dates(make_parquet, run):
    make_parquet("a.parquet", {"d": pa.array([datetime.date(2024, 7, 2), datetime.date(2024, 7, 1)], pa.date32())})
    proc = run("--output", "-", "--key", "d", "a.parquet")
    assert rows_of(proc.stdout)[1:] == [["2024-07-01"], ["2024-07-02"]]


# Spec: "Parquet values come typed" with "timestamp normalized to UTC with `Z`"
def test_timestamp_columns_are_normalised_to_utc(make_parquet, run):
    berlin = datetime.timezone(datetime.timedelta(hours=2))
    stamps = pa.array([datetime.datetime(2024, 7, 1, 12, 0, tzinfo=berlin)], pa.timestamp("us", tz="+02:00"))
    make_parquet("a.parquet", {"ts": stamps})
    proc = run("--output", "-", "--key", "ts", "a.parquet")
    assert rows_of(proc.stdout)[1] == ["2024-07-01T10:00:00Z"]


# Spec: "If JSONL/Parquet value is `null` ... treat as missing -> emit null literal"
def test_parquet_nulls_are_emitted_as_the_null_literal(make_parquet, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "v": pa.array([None], pa.int64())})
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.parquet")
    assert rows_of(proc.stdout)[1] == ["1", "NA"]


# Spec: "**Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6"
def test_list_column_exits_6(make_parquet, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "tags": pa.array([["x"]])})
    proc = run("--output", "-", "--key", "id", "a.parquet", expect_ok=False)
    assert proc.returncode == 6
    assert proc.stderr.strip()


# Spec: "flat schemas only (no nested/list/map types)"
def test_struct_column_exits_6(make_parquet, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "meta": pa.array([{"x": 1}])})
    proc = run("--output", "-", "--key", "id", "a.parquet", expect_ok=False)
    assert proc.returncode == 6


# Spec: "flat schemas only (no nested/list/map types)"
def test_map_column_exits_6(make_parquet, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "m": pa.array([[("k", 1)]], pa.map_(pa.string(), pa.int64()))})
    proc = run("--output", "-", "--key", "id", "a.parquet", expect_ok=False)
    assert proc.returncode == 6


# Spec: "nested fields trigger error 6"
# Context: the schema is rejected even when a provided --schema never selects the column.
def test_nested_column_is_rejected_even_when_not_selected(make_parquet, make_schema, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "tags": pa.array([["x"]])})
    make_schema("s.json", [("id", "int")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.parquet", expect_ok=False)
    assert proc.returncode == 6


# Spec: "Parquet reading must be streamed row group-wise"
# Context: a multi row group file is read whole, in order, under a small memory limit.
def test_multi_row_group_file_is_read_completely(make_parquet, run, workdir):
    ids = list(range(2000))
    make_parquet("a.parquet", {"id": pa.array(ids[::-1]), "pad": pa.array(["x" * 200] * 2000)})
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.parquet")
    rows = rows_of((workdir / "out.csv").read_text())
    assert [int(value) for value in column(rows, "id")] == ids


# Spec: "Extra input columns ignored; missing columns filled with null literal"
def test_provided_schema_selects_parquet_columns(make_parquet, make_schema, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "extra": pa.array(["drop"])})
    make_schema("s.json", [("id", "int"), ("absent", "string")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.parquet")
    assert rows_of(proc.stdout) == [["id", "absent"], ["1", ""]]


# Spec: "Column order: ascending lexicographic by column name"
# Context: the parquet field order is not the output order.
def test_parquet_field_order_is_replaced_by_lexicographic_order(make_parquet, run):
    make_parquet("a.parquet", {"zeta": pa.array([1]), "alpha": pa.array([2])})
    proc = run("--output", "-", "--key", "alpha", "a.parquet")
    assert rows_of(proc.stdout)[0] == ["alpha", "zeta"]


# Spec: "For gzip, allow `.gz` suffix after base extension"
def test_gzipped_parquet_is_read(make_parquet, gzipped, run):
    gzipped(make_parquet("a.parquet", {"id": pa.array([1])}))
    proc = run("--output", "-", "--key", "id", "a.parquet.gz")
    assert rows_of(proc.stdout) == [["id"], ["1"]]
