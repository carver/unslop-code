"""The `Memory & External Merge` section of the partitioned-output spec."""
from pathlib import Path

from conftest import column, data_rows, run, tree, write


# --- Spec: "Continue to honor small `--memory-limit-mb` values" -----------
def test_small_memory_limit_with_sharding(tmp_path):
    rows = "".join(f"{i:05d},{'p' * 40}\n" for i in range(2000, 0, -1))
    a = write(tmp_path, "a.csv", "id,pad\n" + rows)
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
            "--max-rows-per-file", "250", str(a))
    assert r.ok, r
    assert len(tree(out)) == 8
    seen = [value for rel in tree(out) for value in column(out / rel, "id")]
    assert seen == [str(i) for i in range(1, 2001)]


# --- Spec: "Continue to honor small `--memory-limit-mb` values" with field
#     partitioning ---------------------------------------------------------
def test_small_memory_limit_with_partitions(tmp_path):
    rows = "".join(f"{i:05d},g{i % 7},{'p' * 40}\n" for i in range(1500, 0, -1))
    a = write(tmp_path, "a.csv", "id,g,pad\n" + rows)
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
            "--partition-by", "g", str(a))
    assert r.ok, r
    assert len(tree(out)) == 7
    for rel in tree(out):
        ids = [int(v) for v in column(out / rel, "id")]
        assert ids == sorted(ids)
    total = sum(len(data_rows(out / rel)) for rel in tree(out))
    assert total == 1500


# --- Spec: "Tool must work on arbitrarily large inputs": spill files are
#     honoured via --temp-dir and cleaned up afterwards ---------------------
def test_temp_dir_used_and_cleaned(tmp_path):
    rows = "".join(f"{i:05d},{'p' * 60}\n" for i in range(1200, 0, -1))
    a = write(tmp_path, "a.csv", "id,pad\n" + rows)
    spill = tmp_path / "spill"
    spill.mkdir()
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
            "--temp-dir", str(spill), "--max-rows-per-file", "500", str(a))
    assert r.ok, r
    assert list(spill.iterdir()) == []
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]


# --- Spec: "Tool must work on arbitrarily large inputs": many partitions do
#     not require one open file handle per partition ------------------------
def test_many_partitions(tmp_path):
    rows = "".join(f"{i:05d},k{i % 400:03d}\n" for i in range(800, 0, -1))
    a = write(tmp_path, "a.csv", "id,k\n" + rows)
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--memory-limit-mb", "1",
            "--partition-by", "k", str(a))
    assert r.ok, r
    files = tree(out)
    assert len(files) == 400
    assert files[0] == "k=k000/part-00000.csv"
    for rel in files:
        assert len(data_rows(out / rel)) == 2
