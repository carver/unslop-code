"""The `Partitioning by Fields` section of the partitioned-output spec."""
from pathlib import Path

from conftest import (data_rows, dirs, read_rows, read_text, run, tree, write,
                      write_jsonl, write_schema)


def merge_dir(tmp_path, files, *args, out="out"):
    paths = [write(tmp_path, n, t) for n, t in files.items()]
    target = Path(tmp_path) / out
    return run("--output", str(target), *args, *paths, cwd=tmp_path), target


# --- Spec: "Rows for each unique combination of partition column values go
#     into separate directory" ---------------------------------------------
def test_one_directory_per_unique_value(tmp_path):
    files = {"a.csv": "id,c\n1,us\n2,de\n3,us\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=de/part-00000.csv", "c=us/part-00000.csv"]


# --- Spec: "Emit directory tree inside `--output` using Hive-style segments:
#     `<col1>=<val1>/<col2>=<val2>/.../`" -----------------------------------
def test_nested_hive_segments_in_flag_order(tmp_path):
    files = {"a.csv": "id,c,dt\n1,us,2024-01-01\n2,de,2024-01-02\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c,dt")
    assert r.ok, r
    assert tree(out) == [
        "c=de/dt=2024-01-02/part-00000.csv",
        "c=us/dt=2024-01-01/part-00000.csv",
    ]


# --- Spec: "`--partition-by <col>[,<col>...]`": the flag may also be repeated
#     and nesting follows the given order, not schema order -----------------
def test_partition_by_repeated_flag_order(tmp_path):
    files = {"a.csv": "id,c,dt\n1,us,2024-01-01\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id",
                       "--partition-by", "dt", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["dt=2024-01-01/c=us/part-00000.csv"]


# --- Spec: "Values derived after casting to resolved schema types" ---------
def test_values_use_cast_representation(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("id", "int"), ("ok", "bool"), ("n", "int")])
    a = write(tmp_path, "a.csv", "id,ok,n\n1,1,007\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--schema", str(schema),
            "--partition-by", "ok,n", str(a))
    assert r.ok, r
    assert tree(out) == ["ok=true/n=7/part-00000.csv"]


# --- Spec: "Values derived after casting to resolved schema types" -- a
#     timestamp is normalised to UTC before it becomes a segment ------------
def test_timestamp_partition_value_normalised(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("ts", "timestamp")])
    a = write(tmp_path, "a.csv", "id,ts\n1,2024-07-01T12:00:00+02:00\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--schema", str(schema),
            "--partition-by", "ts", str(a))
    assert r.ok, r
    assert tree(out) == ["ts=2024-07-01T10%3A00%3A00Z/part-00000.csv"]


# --- Spec: "Apply percent-encoding of UTF-8 bytes for characters outside
#     `[A-Za-z0-9._-]`" ----------------------------------------------------
def test_safe_characters_are_not_encoded(tmp_path):
    files = {"a.csv": "id,c\n1,aZ9._-\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=aZ9._-/part-00000.csv"]


# --- Spec: "space → `%20`" -------------------------------------------------
def test_space_percent_encoded(tmp_path):
    files = {"a.csv": "id,c\n1,new york\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=new%20york/part-00000.csv"]


# --- Spec: "`/` encoded as `%2F`" (uppercase hex, no directory split) ------
def test_slash_percent_encoded(tmp_path):
    files = {"a.csv": "id,c\n1,a/b\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=a%2Fb/part-00000.csv"]
    assert dirs(out) == ["c=a%2Fb"]


# --- Spec: "percent-encoding of UTF-8 bytes": multi-byte characters encode
#     one `%XX` per UTF-8 byte ---------------------------------------------
def test_utf8_bytes_encoded_individually(tmp_path):
    files = {"a.csv": "id,c\n1,é\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=%C3%A9/part-00000.csv"]


# --- Spec: "characters outside `[A-Za-z0-9._-]`": `=` and `%` are outside it
def test_equals_and_percent_encoded(tmp_path):
    files = {"a.csv": "id,c\n1,a=b\n2,100%\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=100%25/part-00000.csv", "c=a%3Db/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`" -----------
def test_missing_partition_value_is_null_literal(tmp_path):
    files = {"a.csv": "id,c\n1,us\n", "b.csv": "id\n2\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=_null/part-00000.csv", "c=us/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`": an empty
#     cell is null too -----------------------------------------------------
def test_empty_partition_value_is_null_literal(tmp_path):
    files = {"a.csv": "id,c\n1,\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=_null/part-00000.csv"]


# --- Spec: "Null (missing) partition values use literal `_null`": a JSON null
def test_json_null_partition_value(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "c": None}])
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "c", str(a))
    assert r.ok, r
    assert tree(out) == ["c=_null/part-00000.csv"]


# --- Spec: "Within each partition directory, write CSV files named
#     sequentially: `part-00000.csv`, ... (zero-padded width 5)" ------------
def test_part_name_zero_padded_width_five(tmp_path):
    files = {"a.csv": "id,c\n1,us\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=us/part-00000.csv"]


# --- Spec: "Each file contains header row (resolved schema header)" --------
def test_every_partition_file_has_the_schema_header(tmp_path):
    files = {"a.csv": "id,c,extra\n1,us,x\n2,de,y\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    # The resolved header is the union of input columns, in schema order.
    for rel in tree(out):
        assert read_rows(out / rel)[0] == ["c", "extra", "id"]


# --- Spec: "otherwise one file per partition" (no cutting flags) ----------
def test_one_file_per_partition_without_limits(tmp_path):
    files = {"a.csv": "id,c\n" + "".join(f"{i},us\n" for i in range(50))}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert tree(out) == ["c=us/part-00000.csv"]
    assert len(data_rows(out / "c=us" / "part-00000.csv")) == 50


# --- Spec: "Rows for each unique combination": rows land in the directory
#     matching their own values, and nowhere else --------------------------
def test_rows_land_in_matching_partition(tmp_path):
    files = {"a.csv": "id,c\n1,us\n2,de\n3,us\n"}
    r, out = merge_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert data_rows(out / "c=us" / "part-00000.csv") == [["us", "1"], ["us", "3"]]
    assert data_rows(out / "c=de" / "part-00000.csv") == [["de", "2"]]


# --- Spec: "Emit directory tree inside `--output`": a partition column that
#     is not in the resolved schema is a schema error ----------------------
def test_unknown_partition_column_rejected(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "nope", str(a))
    assert r.returncode == 3, r
    assert "nope" in r.stderr
    assert not out.exists()
