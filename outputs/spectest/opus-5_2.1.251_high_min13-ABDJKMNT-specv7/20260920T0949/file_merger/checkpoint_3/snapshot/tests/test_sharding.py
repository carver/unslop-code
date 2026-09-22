"""Cutting the sorted stream into part files by row count and by byte size."""

from conftest import rows_of


def _numbered(count, payload="xxxx"):
    """A CSV whose rows are `id,payload` with ids counting up from 1."""
    return "id,payload\n" + "".join(f"{i},{payload}\n" for i in range(1, count + 1))


# Spec: "`--max-rows-per-file <INT>`: cut output into files with at most INT
# data rows each"
def test_files_hold_at_most_the_row_limit(make_csv, run, tree, read):
    make_csv("a.csv", _numbered(7))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "3", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [len(rows_of(read(f"out/{name}"))) - 1 for name in tree("out")] == [3, 3, 1]


# Spec: "cut output into files with at most INT data rows each (header not counted)"
def test_the_header_does_not_count_towards_the_row_limit(make_csv, run, read):
    make_csv("a.csv", _numbered(2))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert read("out/part-00000.csv").count("\n") == 3


# Spec: "`--max-bytes-per-file <INT>`: cut so on-disk byte size of each file
# (including header and line endings) is <= INT"
def test_every_file_stays_within_the_byte_limit(make_csv, run, tree, workdir):
    make_csv("a.csv", _numbered(6))
    run("--output", "out", "--key", "id", "--max-bytes-per-file", "25", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert all((workdir / "out" / name).stat().st_size <= 25 for name in tree("out"))


# Spec: "cut so on-disk byte size of each file (including header and line
# endings) is <= INT"
# Context: a limit of exactly header+row admits one row per file.
def test_byte_limit_counts_the_header_of_every_file(make_csv, run, tree, read):
    make_csv("a.csv", _numbered(3))
    run("--output", "out", "--key", "id", "--max-bytes-per-file", "18", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert read("out/part-00000.csv") == "id,payload\n1,xxxx\n"


# Spec: "Exception: if single row alone exceeds INT, place that row in file by
# itself (allowed to exceed limit)"
def test_an_oversized_row_gets_a_file_of_its_own(make_csv, run, tree, workdir):
    make_csv("a.csv", _numbered(2, payload="y" * 50))
    run("--output", "out", "--key", "id", "--max-bytes-per-file", "20", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv"]
    assert all((workdir / "out" / name).stat().st_size > 20 for name in tree("out"))


# Spec: "Exception: if single row alone exceeds INT ..."
# Context: an oversized row does not drag along the rows around it.
def test_small_rows_around_an_oversized_row_are_not_merged_into_it(make_csv, run, read):
    make_csv("a.csv", "id,payload\n1,a\n2," + "y" * 50 + "\n3,c\n")
    run("--output", "out", "--key", "id", "--max-bytes-per-file", "20", "a.csv")
    assert rows_of(read("out/part-00000.csv")) == [["id", "payload"], ["1", "a"]]
    assert rows_of(read("out/part-00001.csv"))[1] == ["2", "y" * 50]
    assert rows_of(read("out/part-00002.csv")) == [["id", "payload"], ["3", "c"]]


# Spec: "When both `--max-rows-per-file` and `--max-bytes-per-file` provided,
# cut at earliest boundary that would violate either constraint"
# Context: here the row limit is reached first.
def test_row_limit_wins_when_it_is_the_earlier_boundary(make_csv, run, tree):
    make_csv("a.csv", _numbered(6))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "--max-bytes-per-file", "1000", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]


# Spec: "cut at earliest boundary that would violate either constraint"
# Context: here the byte limit is reached first.
def test_byte_limit_wins_when_it_is_the_earlier_boundary(make_csv, run, read):
    make_csv("a.csv", _numbered(6))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "5", "--max-bytes-per-file", "25", "a.csv")
    assert rows_of(read("out/part-00000.csv")) == [["id", "payload"], ["1", "xxxx"], ["2", "xxxx"]]


# Spec: "File naming (no field partitioning): write files directly under
# `--output` as `part-00000.csv`, `part-00001.csv`, ..."
def test_shards_sit_directly_under_the_output_directory(make_csv, run, tree):
    make_csv("a.csv", _numbered(3))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv")
    assert tree("out") == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]


# Spec: "... in exact order rows are emitted from sorted stream"
def test_shard_order_follows_the_sorted_stream(make_csv, run, read):
    make_csv("a.csv", "id,payload\n5,e\n1,a\n3,c\n2,b\n4,d\n")
    run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert rows_of(read("out/part-00000.csv"))[1:] == [["1", "a"], ["2", "b"]]
    assert rows_of(read("out/part-00001.csv"))[1:] == [["3", "c"], ["4", "d"]]
    assert rows_of(read("out/part-00002.csv"))[1:] == [["5", "e"]]


# Spec: "With no field partitioning: rows must be globally sorted by `--key`
# (and `--desc` if set)"
def test_desc_orders_the_whole_sharded_stream(make_csv, run, read):
    make_csv("a.csv", _numbered(5))
    run("--output", "out", "--key", "id", "--desc", "--max-rows-per-file", "2", "a.csv")
    assert rows_of(read("out/part-00000.csv"))[1:] == [["5", "xxxx"], ["4", "xxxx"]]
    assert rows_of(read("out/part-00002.csv"))[1:] == [["1", "xxxx"]]


# Spec: "File naming (with field partitioning): same `part-xxxxx.csv` sequence
# per partition directory"
def test_each_partition_restarts_the_part_sequence(make_csv, run, tree):
    make_csv("a.csv", "id,g\n1,a\n2,a\n3,a\n4,b\n5,b\n6,b\n")
    run("--output", "out", "--key", "id", "--partition-by", "g", "--max-rows-per-file", "2", "a.csv")
    assert tree("out") == [
        "g=a/part-00000.csv",
        "g=a/part-00001.csv",
        "g=b/part-00000.csv",
        "g=b/part-00001.csv",
    ]


# Spec: "Every output CSV includes header row in resolved schema column order"
# Context: each shard of a sharded stream repeats the header.
def test_every_shard_repeats_the_header(make_csv, run, read, tree):
    make_csv("a.csv", _numbered(3))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv")
    assert all(read(f"out/{name}").startswith("id,payload\n") for name in tree("out"))


# Spec: "Tool must work on arbitrarily large inputs" with
# "Continue to honor small `--memory-limit-mb` values"
def test_sharding_survives_a_spilling_sort(make_csv, run, read, tree):
    make_csv("a.csv", _numbered(5000))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "700", "--memory-limit-mb", "1", "a.csv")
    names = tree("out")
    assert names == [f"part-{i:05d}.csv" for i in range(8)]
    ids = [int(row[0]) for name in names for row in rows_of(read(f"out/{name}"))[1:]]
    assert ids == sorted(ids) and len(ids) == 5000


# Spec: "--max-rows-per-file <INT>" - a limit of zero rows cannot be honoured
# (AMBIGUITIES T44).
def test_zero_row_limit_is_a_usage_error(make_csv, run):
    make_csv("a.csv", _numbered(1))
    proc = run("--output", "out", "--key", "id", "--max-rows-per-file", "0", "a.csv", expect_ok=False)
    assert proc.returncode == 2
