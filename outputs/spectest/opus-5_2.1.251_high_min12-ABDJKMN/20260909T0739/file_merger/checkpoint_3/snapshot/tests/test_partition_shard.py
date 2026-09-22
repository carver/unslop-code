"""The `Partitioning by Size or Rows` (sharding) section of the spec."""
import os
from pathlib import Path

from conftest import data_rows, read_rows, read_text, run, tree, write


def shard(tmp_path, text, *args, name="a.csv", out="out"):
    a = write(tmp_path, name, text)
    target = Path(tmp_path) / out
    r = run("--output", str(target), *args, str(a), cwd=tmp_path)
    return r, target


# --- Spec: "`--max-rows-per-file <INT>`: cut output into files with at most
#     INT data rows each (header not counted)" -----------------------------
def test_max_rows_cuts_at_row_count(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(5))
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "2")
    assert r.ok, r
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert data_rows(out / "part-00000.csv") == [["0"], ["1"]]
    assert data_rows(out / "part-00001.csv") == [["2"], ["3"]]
    assert data_rows(out / "part-00002.csv") == [["4"]]


# --- Spec: "(header not counted)": each shard carries its own header on top
#     of the INT data rows -------------------------------------------------
def test_header_not_counted_towards_max_rows(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(4))
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "2")
    assert r.ok, r
    assert read_text(out / "part-00000.csv") == "id\n0\n1\n"
    assert read_text(out / "part-00001.csv") == "id\n2\n3\n"


# --- Spec: "cut output into files with at most INT data rows each": an exact
#     multiple produces no trailing empty file ------------------------------
def test_exact_multiple_has_no_trailing_file(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(4))
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "2")
    assert r.ok, r
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]


# --- Spec: "--max-rows-per-file 1" is the smallest legal cut ---------------
def test_max_rows_one_row_per_file(tmp_path):
    text = "id\n3\n1\n2\n"
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "1")
    assert r.ok, r
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [data_rows(out / n)[0][0] for n in sorted(tree(out))] == ["1", "2", "3"]


# --- Spec: "`--max-bytes-per-file <INT>`: cut so on-disk byte size of each
#     file (including header and line endings) is ≤ INT" -------------------
def test_max_bytes_respects_on_disk_size(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(10))
    # header "id\n" = 3 bytes, each row "N\n" = 2 bytes -> 4 rows fit in 11.
    r, out = shard(tmp_path, text, "--key", "id", "--max-bytes-per-file", "11")
    assert r.ok, r
    for rel in tree(out):
        assert os.path.getsize(out / rel) <= 11, rel
    assert data_rows(out / "part-00000.csv") == [["0"], ["1"], ["2"], ["3"]]


# --- Spec: "on-disk byte size ... (including header and line endings)":
#     every emitted row appears exactly once, in order ---------------------
def test_max_bytes_keeps_every_row_once(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(30))
    r, out = shard(tmp_path, text, "--key", "id", "--max-bytes-per-file", "20")
    assert r.ok, r
    seen = []
    for rel in tree(out):
        seen.extend(row[0] for row in data_rows(out / rel))
    assert seen == [str(i) for i in range(30)]


# --- Spec: "Exception: if single row alone exceeds INT, place that row in
#     file by itself (allowed to exceed limit)" ----------------------------
def test_oversized_row_gets_its_own_file(tmp_path):
    big = "x" * 100
    text = f"id,v\n1,a\n2,{big}\n3,b\n"
    r, out = shard(tmp_path, text, "--key", "id", "--max-bytes-per-file", "12")
    assert r.ok, r
    files = tree(out)
    assert len(files) == 3, files
    assert data_rows(out / "part-00000.csv") == [["1", "a"]]
    assert data_rows(out / "part-00001.csv") == [["2", big]]
    assert data_rows(out / "part-00002.csv") == [["3", "b"]]
    assert os.path.getsize(out / "part-00001.csv") > 12


# --- Spec: "if single row alone exceeds INT, place that row in file by
#     itself": a limit below even the header still emits the rows ----------
def test_tiny_byte_limit_still_emits_all_rows(tmp_path):
    text = "id,v\n1,aaa\n2,bbb\n"
    r, out = shard(tmp_path, text, "--key", "id", "--max-bytes-per-file", "1")
    assert r.ok, r
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]
    assert data_rows(out / "part-00000.csv") == [["1", "aaa"]]
    assert data_rows(out / "part-00001.csv") == [["2", "bbb"]]


# --- Spec: "When both `--max-rows-per-file` and `--max-bytes-per-file`
#     provided, cut at earliest boundary that would violate either
#     constraint" -- here the row limit binds first -------------------------
def test_both_limits_row_limit_binds(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(6))
    r, out = shard(tmp_path, text, "--key", "id",
                   "--max-rows-per-file", "2", "--max-bytes-per-file", "1000")
    assert r.ok, r
    assert [len(data_rows(out / rel)) for rel in tree(out)] == [2, 2, 2]


# --- Spec: "cut at earliest boundary that would violate either constraint"
#     -- here the byte limit binds first ------------------------------------
def test_both_limits_byte_limit_binds(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(6))
    r, out = shard(tmp_path, text, "--key", "id",
                   "--max-rows-per-file", "100", "--max-bytes-per-file", "7")
    assert r.ok, r
    for rel in tree(out):
        assert os.path.getsize(out / rel) <= 7
    assert [len(data_rows(out / rel)) for rel in tree(out)] == [2, 2, 2]


# --- Spec: "File naming (no field partitioning): write files directly under
#     `--output` as `part-00000.csv`, `part-00001.csv`, ..." ---------------
def test_shards_written_directly_under_output(tmp_path):
    text = "id\n" + "".join(f"{i}\n" for i in range(3))
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "1")
    assert r.ok, r
    assert sorted(p.name for p in out.iterdir()) == [
        "part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert all(p.is_file() for p in out.iterdir())


# --- Spec: "... in exact order rows are emitted from sorted stream" -------
def test_shard_order_follows_sorted_stream(tmp_path):
    text = "id\n5\n3\n1\n4\n2\n"
    r, out = shard(tmp_path, text, "--key", "id", "--max-rows-per-file", "2")
    assert r.ok, r
    assert data_rows(out / "part-00000.csv") == [["1"], ["2"]]
    assert data_rows(out / "part-00001.csv") == [["3"], ["4"]]
    assert data_rows(out / "part-00002.csv") == [["5"]]


# --- Spec: "... in exact order rows are emitted from sorted stream", with
#     `--desc` ---------------------------------------------------------------
def test_shard_order_follows_desc_stream(tmp_path):
    text = "id\n1\n2\n3\n"
    r, out = shard(tmp_path, text, "--key", "id", "--desc",
                   "--max-rows-per-file", "2")
    assert r.ok, r
    assert data_rows(out / "part-00000.csv") == [["3"], ["2"]]
    assert data_rows(out / "part-00001.csv") == [["1"]]


# --- Spec: "File naming (with field partitioning): same `part-xxxxx.csv`
#     sequence per partition directory" ------------------------------------
def test_shard_sequence_restarts_per_partition(tmp_path):
    text = "id,c\n1,us\n2,us\n3,us\n4,de\n5,de\n"
    r, out = shard(tmp_path, text, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "2")
    assert r.ok, r
    assert tree(out) == [
        "c=de/part-00000.csv",
        "c=us/part-00000.csv",
        "c=us/part-00001.csv",
    ]
    assert data_rows(out / "c=de" / "part-00000.csv") == [["de", "4"], ["de", "5"]]
    assert data_rows(out / "c=us" / "part-00001.csv") == [["us", "3"]]


# --- Spec: sharded partition files each carry the header ------------------
def test_sharded_partition_files_have_headers(tmp_path):
    text = "id,c\n1,us\n2,us\n3,us\n"
    r, out = shard(tmp_path, text, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "1")
    assert r.ok, r
    for rel in tree(out):
        assert read_rows(out / rel)[0] == ["c", "id"]


# --- Spec: "at most INT data rows": a non-positive limit is a usage error --
def test_zero_max_rows_rejected(tmp_path):
    r, out = shard(tmp_path, "id\n1\n", "--key", "id", "--max-rows-per-file", "0")
    assert r.returncode == 2, r
    assert not out.exists()


def test_negative_max_bytes_rejected(tmp_path):
    r, out = shard(tmp_path, "id\n1\n", "--key", "id", "--max-bytes-per-file", "-5")
    assert r.returncode == 2, r
    assert not out.exists()
