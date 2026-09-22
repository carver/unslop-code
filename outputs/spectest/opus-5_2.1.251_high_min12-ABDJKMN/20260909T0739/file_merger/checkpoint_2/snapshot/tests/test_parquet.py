"""`Source Dialect Assumptions`: Parquet."""
from conftest import (merge_paths, pa_modules, write, write_parquet,
                      write_schema)


# --- Spec: "Accepted file types: ... Parquet" / "Parquet values come typed"
def test_parquet_typed_values_are_cast(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()), ("amount", pa.float64()),
                        ("flag", pa.bool_()), ("name", pa.string())])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "amount": 2.5, "flag": True, "name": "x"}],
                      schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["amount", "flag", "id", "name"],
                        ["2.5", "true", "1", "x"]]


# --- Spec: "Parquet: flat schemas only (no nested/list/map types); nested
#            fields trigger error 6" ---------------------------------------
def test_list_column_is_error_6(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()), ("tags", pa.list_(pa.string()))])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "tags": ["x"]}], schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r
    assert r.stderr.strip()


def test_struct_column_is_error_6(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()),
                        ("meta", pa.struct([("k", pa.int64())]))])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "meta": {"k": 2}}], schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


def test_map_column_is_error_6(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()),
                        ("m", pa.map_(pa.string(), pa.int64()))])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "m": [("k", 2)]}], schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


# --- Spec: "flat schemas only" - a nested column that holds only nulls is
#            still a schema-level violation --------------------------------
def test_all_null_list_column_is_error_6(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()), ("tags", pa.list_(pa.string()))])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "tags": None}], schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


# --- Spec: "If JSONL/Parquet value is `null` ... treat as missing -> emit
#            null literal" -------------------------------------------------
def test_parquet_null_renders_as_null_literal(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()), ("name", pa.string())])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "name": None}], schema=schema)
    r = merge_paths([a], "--key", "id", "--csv-null-literal", "NA")
    assert r.ok, r
    assert r.rows()[1] == ["1", "NA"]


# --- Spec: "Parquet values come typed" - temporal columns arrive as real
#            timestamps and normalise to UTC ------------------------------
def test_parquet_timestamp_column(tmp_path):
    pa, _ = pa_modules()
    import datetime as dt
    schema = pa.schema([("id", pa.int64()),
                        ("ts", pa.timestamp("us", tz="UTC"))])
    a = write_parquet(
        tmp_path, "a.parquet",
        [{"id": 1, "ts": dt.datetime(2024, 7, 1, 12, 0, tzinfo=dt.timezone.utc)}],
        schema=schema,
    )
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["1", "2024-07-01T12:00:00Z"]


def test_parquet_date_column(tmp_path):
    pa, _ = pa_modules()
    import datetime as dt
    schema = pa.schema([("id", pa.int64()), ("d", pa.date32())])
    a = write_parquet(tmp_path, "a.parquet",
                      [{"id": 1, "d": dt.date(2024, 7, 1)}], schema=schema)
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01", "1"]


# --- Spec: "Parquet reading must be streamed row group-wise" - a multi-row
#            group file still yields every row exactly once ----------------
def test_multiple_row_groups_all_rows_once(tmp_path):
    records = [{"id": i, "v": f"r{i}"} for i in range(50)]
    a = write_parquet(tmp_path, "a.parquet", records, row_group_size=7)
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    rows = r.rows()
    assert len(rows) == 51
    assert [row[0] for row in rows[1:]] == [str(i) for i in range(50)]


# --- Spec: "--parquet-row-group-bytes <INT> is advisory for batch sizing" -
def test_row_group_bytes_flag_does_not_change_output(tmp_path):
    records = [{"id": i, "v": f"r{i}"} for i in range(20)]
    a = write_parquet(tmp_path, "a.parquet", records, row_group_size=5)
    base = merge_paths([a], "--key", "id")
    tuned = merge_paths([a], "--key", "id", "--parquet-row-group-bytes", "4096")
    assert base.ok and tuned.ok, (base, tuned)
    assert base.stdout == tuned.stdout


# --- Spec: "Column set: union of all encountered field names" - parquet
#            columns join the union ---------------------------------------
def test_parquet_columns_join_the_union(tmp_path):
    p = write_parquet(tmp_path, "a.parquet", [{"id": 1, "only_p": "p"}])
    c = write(tmp_path, "b.csv", "id,only_c\n2,c\n")
    r = merge_paths([p, c], "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["id", "only_c", "only_p"]
    assert r.rows()[1] == ["1", "", "p"]
    assert r.rows()[2] == ["2", "c", ""]


# --- Spec: "If `--schema` provided, it defines exact output columns" ------
def test_schema_projects_parquet_columns(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("id", "int"), ("missing", "string")])
    a = write_parquet(tmp_path, "a.parquet", [{"id": 1, "extra": "e"}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["id", "missing"], ["1", ""]]
