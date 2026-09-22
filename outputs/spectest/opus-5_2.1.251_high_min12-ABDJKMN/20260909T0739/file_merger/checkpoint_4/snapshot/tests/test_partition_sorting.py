"""The `Sorting Guarantees` section of the partitioned-output spec."""
from pathlib import Path

from conftest import column, data_rows, read_rows, run, tree, write, write_schema


def out_dir(tmp_path, files, *args):
    paths = [write(tmp_path, n, t) for n, t in files.items()]
    target = Path(tmp_path) / "out"
    return run("--output", str(target), *args, *paths, cwd=tmp_path), target


def stream(out, name):
    """Values of column `name` across every part file, in part order."""
    values = []
    for rel in tree(out):
        values.extend(column(out / rel, name))
    return values


# --- Spec: "With no field partitioning: rows must be globally sorted by
#     `--key`" -------------------------------------------------------------
def test_global_sort_across_shards(tmp_path):
    files = {"a.csv": "id\n5\n1\n", "b.csv": "id\n3\n2\n4\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--max-rows-per-file", "2")
    assert r.ok, r
    assert stream(out, "id") == ["1", "2", "3", "4", "5"]


# --- Spec: "With no field partitioning: ... (and `--desc` if set)" ---------
def test_global_sort_desc_across_shards(tmp_path):
    files = {"a.csv": "id\n5\n1\n", "b.csv": "id\n3\n2\n4\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--desc",
                     "--max-rows-per-file", "2")
    assert r.ok, r
    assert stream(out, "id") == ["5", "4", "3", "2", "1"]


# --- Spec: "globally sorted by `--key`" -- composite key ------------------
def test_global_sort_composite_key(tmp_path):
    files = {"a.csv": "ts,id\n2,b\n1,b\n2,a\n1,a\n"}
    r, out = out_dir(tmp_path, files, "--key", "ts,id", "--max-rows-per-file", "3")
    assert r.ok, r
    assert stream(out, "ts") == ["1", "1", "2", "2"]
    assert stream(out, "id") == ["a", "b", "a", "b"]


# --- Spec: "With field partitioning: rows in each partition directory must
#     be sorted by `--key` within that partition" --------------------------
def test_rows_sorted_within_each_partition(tmp_path):
    files = {"a.csv": "id,c\n3,us\n1,de\n2,us\n4,de\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert column(out / "c=us" / "part-00000.csv", "id") == ["2", "3"]
    assert column(out / "c=de" / "part-00000.csv", "id") == ["1", "4"]


# --- Spec: "rows in each partition directory must be sorted by `--key`
#     within that partition", with `--desc` and sharding -------------------
def test_partition_sort_desc_across_shards(tmp_path):
    files = {"a.csv": "id,c\n1,us\n3,us\n2,us\n5,de\n4,de\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--desc",
                     "--partition-by", "c", "--max-rows-per-file", "2")
    assert r.ok, r
    us = [value for rel in ["c=us/part-00000.csv", "c=us/part-00001.csv"]
          for value in column(out / rel, "id")]
    assert us == ["3", "2", "1"]
    assert column(out / "c=de" / "part-00000.csv", "id") == ["5", "4"]


# --- Spec: sorting is by the typed key, not lexicographic text ------------
def test_partition_sort_uses_typed_key(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("c", "string")])
    files = {"a.csv": "id,c\n10,us\n9,us\n100,us\n"}
    paths = [write(tmp_path, n, t) for n, t in files.items()]
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--schema", str(schema),
            "--partition-by", "c", *[str(p) for p in paths])
    assert r.ok, r
    assert column(out / "c=us" / "part-00000.csv", "id") == ["9", "10", "100"]


# --- Spec: sorting is stable in input order for equal keys ----------------
def test_ties_keep_input_order_within_partition(tmp_path):
    files = {"a.csv": "id,c,v\n1,us,first\n1,us,second\n"}
    r, out = out_dir(tmp_path, files, "--key", "id", "--partition-by", "c")
    assert r.ok, r
    assert column(out / "c=us" / "part-00000.csv", "v") == ["first", "second"]
