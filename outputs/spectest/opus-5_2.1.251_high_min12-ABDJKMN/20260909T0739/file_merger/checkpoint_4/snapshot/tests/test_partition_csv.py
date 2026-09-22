"""The `CSV Output Contents` section of the partitioned-output spec."""
from pathlib import Path

from conftest import (data_rows, read_rows, read_text, run, tree, write,
                      write_schema)


def out_dir(tmp_path, files, *args):
    paths = [write(tmp_path, n, t) for n, t in files.items()]
    target = Path(tmp_path) / "out"
    return run("--output", str(target), *args, *paths, cwd=tmp_path), target


# --- Spec: "Every output CSV includes header row in resolved schema column
#     order" ---------------------------------------------------------------
def test_header_in_schema_order(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("id", "int"), ("c", "string"), ("v", "string")])
    a = write(tmp_path, "a.csv", "v,c,id\nx,us,1\ny,de,2\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--schema", str(schema),
            "--partition-by", "c", str(a))
    assert r.ok, r
    for rel in tree(out):
        assert read_rows(out / rel)[0] == ["id", "c", "v"]
    assert data_rows(out / "c=us" / "part-00000.csv") == [["1", "us", "x"]]


# --- Spec: "Every output CSV includes header row": partition columns are part
#     of the resolved schema and stay in the rows --------------------------
def test_partition_columns_remain_in_rows(tmp_path):
    files = {"a.csv": "id,c\n7,us\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert read_text(out / "c=us" / "part-00000.csv") == "c,id\nus,7\n"


# --- Spec: "Use same delimiter/quote/escape/line-ending/null-literal rules as
#     before" -- quoting -----------------------------------------------------
def test_quoting_rules_apply_in_partition_files(tmp_path):
    files = {"a.csv": 'id,c,v\n7,us,"a,b"\n'}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert read_text(out / "c=us" / "part-00000.csv") == 'c,id,v\nus,7,"a,b"\n'


# --- Spec: "same ... null-literal rules as before" ------------------------
def test_null_literal_applies_in_partition_files(tmp_path):
    files = {"a.csv": "id,c,v\n7,us,\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c",
                     "--csv-null-literal", "NULL")
    assert r.ok, r
    assert read_text(out / "c=us" / "part-00000.csv") == "c,id,v\nus,7,NULL\n"


# --- Spec: "same ... quote ... rules as before" (--csv-quotechar) ---------
def test_custom_quotechar_in_shards(tmp_path):
    files = {"a.csv": "id,v\n7,'a,b'\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--max-rows-per-file", "5",
                     "--csv-quotechar", "'")
    assert r.ok, r
    assert read_text(out / "part-00000.csv") == "id,v\n7,'a,b'\n"


# --- Spec: "same ... line-ending ... rules as before" ---------------------
def test_line_endings_are_lf(tmp_path):
    files = {"a.csv": "id\n8\n9\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--max-rows-per-file", "5")
    assert r.ok, r
    text = read_text(out / "part-00000.csv")
    assert "\r" not in text
    assert text == "id\n8\n9\n"


# --- Spec: "Each partition file is independently valid CSV" --------------
def test_each_file_parses_independently(tmp_path):
    files = {"a.csv": 'id,c,v\n7,us,"x\ny"\n8,de,plain\n'}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    for rel in tree(out):
        rows = read_rows(out / rel)
        assert rows[0] == ["c", "id", "v"]
        assert len(rows) == 2
        assert all(len(row) == 3 for row in rows)


# --- Spec: "Every output CSV includes header row": a shard-only run with no
#     data rows still describes the stream ---------------------------------
def test_empty_stream_writes_header_only_shard(tmp_path):
    files = {"a.csv": "id,v\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--max-rows-per-file", "3")
    assert r.ok, r
    assert tree(out) == ["part-00000.csv"]
    assert read_text(out / "part-00000.csv") == "id,v\n"


# --- Spec: "Rows for each unique combination of partition column values go
#     into separate directory": no rows means no partitions ---------------
def test_empty_stream_with_field_partitioning_makes_empty_dir(tmp_path):
    files = {"a.csv": "id,c\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert out.is_dir()
    assert tree(out) == []
