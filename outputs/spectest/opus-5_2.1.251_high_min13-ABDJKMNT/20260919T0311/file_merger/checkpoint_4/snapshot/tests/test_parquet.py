"""Spec section: Source Dialect Assumptions — Parquet."""
import datetime

import pyarrow as pa
import pyarrow.parquet as pq
from conftest import column, table


# Phrase: "Parquet values come typed"
# Context: T31 — the file's declared schema types the column without sniffing.
def test_declared_string_column_stays_string(run, parquet_file):
    parquet_file("a.parquet", {"id": (["10", "9"], pa.string())})
    assert column(run("--output", "-", "--key", "id", "a.parquet").stdout, "id") == ["10", "9"]


# Phrase: "Parquet values come typed"
# Context: an int64 column sorts numerically and renders canonically.
def test_int_column_sorts_numerically(run, parquet_file):
    parquet_file("a.parquet", {"id": ([10, 9, 100], pa.int64())})
    assert column(run("--output", "-", "--key", "id", "a.parquet").stdout, "id") == [
        "9", "10", "100",
    ]


# Phrase: "Parquet values come typed"
# Context: T32 — bool, float, date32 and timestamp map onto the schema types.
def test_typed_columns_render_canonically(run, parquet_file):
    parquet_file("a.parquet", {
        "id": ([1], pa.int64()),
        "b": ([True], pa.bool_()),
        "f": ([1.5], pa.float64()),
        "d": ([datetime.date(2024, 7, 1)], pa.date32()),
        "t": ([datetime.datetime(2024, 7, 1, 12, 0, 0)], pa.timestamp("us")),
    })
    res = run("--output", "-", "--key", "id", "a.parquet")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["true", "2024-07-01", "1.5", "1", "2024-07-01T12:00:00Z"]


# Phrase: "If JSONL/Parquet value is null ... treat as missing -> emit null literal"
def test_parquet_null_becomes_the_null_literal(run, parquet_file):
    parquet_file("a.parquet", {"id": ([1], pa.int64()), "v": ([None], pa.string())})
    res = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.parquet")
    assert column(res.stdout, "v") == ["NA"]


# Phrase: "Parquet: flat schemas only (no nested/list/map types); nested fields trigger error 6"
# Context: a list column.
def test_list_column_is_error_6(run, parquet_file):
    parquet_file("a.parquet", {"id": ([1], pa.int64()), "v": ([[1, 2]], pa.list_(pa.int64()))})
    res = run("--output", "-", "--key", "id", "a.parquet")
    assert res.returncode == 6
    assert res.stderr.strip().startswith("ERR 6 ")


# Phrase: "flat schemas only (no nested/list/map types)"
# Context: a struct column.
def test_struct_column_is_error_6(run, parquet_file):
    parquet_file("a.parquet", {
        "id": ([1], pa.int64()),
        "v": ([{"k": 1}], pa.struct([("k", pa.int64())])),
    })
    assert run("--output", "-", "--key", "id", "a.parquet").returncode == 6


# Phrase: "flat schemas only (no nested/list/map types)"
# Context: a map column.
def test_map_column_is_error_6(run, parquet_file):
    parquet_file("a.parquet", {
        "id": ([1], pa.int64()),
        "v": ([[("k", 1)]], pa.map_(pa.string(), pa.int64())),
    })
    assert run("--output", "-", "--key", "id", "a.parquet").returncode == 6


# Phrase: "Parquet reading must be streamed row group-wise"
# Context: a many-row-group file still merges correctly under a tight budget.
def test_many_row_groups_stream(run, tmp_path):
    ids = [(i * 7) % 1000 for i in range(1000)]
    pq.write_table(pa.table({"id": pa.array(ids, pa.int64())}),
                   tmp_path / "a.parquet", row_group_size=25)
    res = run("--output", "-", "--key", "id", "--memory-limit-mb", "1", "a.parquet")
    assert res.returncode == 0, res.stderr
    assert [int(v) for v in column(res.stdout, "id")] == sorted(ids)


# Phrase: "Column set: union of all encountered field names"
# Context: a Parquet file with no rows still contributes its schema columns.
def test_empty_parquet_contributes_its_columns(run, parquet_file, csv_file):
    parquet_file("a.parquet", {"id": ([], pa.int64()), "extra": ([], pa.string())})
    csv_file("b.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "a.parquet", "b.csv")
    assert table(res.stdout) == [["extra", "id"], ["", "1"]]


# Phrase: "If --schema provided ... Extra input columns ignored"
def test_schema_ignores_extra_parquet_columns(run, parquet_file, schema_file):
    parquet_file("a.parquet", {"id": ([1], pa.int64()), "noise": (["z"], pa.string())})
    schema = schema_file([("id", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.parquet")
    assert table(res.stdout) == [["id"], ["1"]]


# Phrase: "For gzip, allow .gz suffix after base extension"
# Context: a gzip-wrapped Parquet file is still read row group-wise.
def test_gzipped_parquet(run, tmp_path, parquet_file):
    import gzip

    parquet_file("a.parquet", {"id": ([3, 1], pa.int64())})
    with gzip.open(tmp_path / "a.parquet.gz", "wb") as fh:
        fh.write((tmp_path / "a.parquet").read_bytes())
    res = run("--output", "-", "--key", "id", "a.parquet.gz")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "id") == ["1", "3"]
