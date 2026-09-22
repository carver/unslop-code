"""Spec section: Partitioned Output -> Partitioning by Size or Rows."""
import os

from conftest import read_csv_file, tree


def part_size(root, name):
    return os.path.getsize(str(root / name))


# Phrase: "`--max-rows-per-file <INT>`: cut output into files with at most INT
#          data rows each (header not counted)"
# Context: Partitioning by Size or Rows.
def test_max_rows_cuts_at_exactly_n_data_rows(run, work):
    work.csv("a.csv", ["id"], [[str(i)] for i in range(10)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "3",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == [
        "part-00000.csv", "part-00001.csv", "part-00002.csv", "part-00003.csv",
    ]
    counts = [len(read_csv_file(out / n)) - 1 for n in tree(out)]
    assert counts == [3, 3, 3, 1]


# Phrase: "header not counted"
# Context: every part carries its own header row.
def test_every_shard_repeats_the_header(run, work):
    work.csv("a.csv", ["id", "v"], [[str(i), "x"] for i in range(5)])
    schema = work.schema("s.json", [("id", "int"), ("v", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "2",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    for name in tree(out):
        assert read_csv_file(out / name)[0] == ["id", "v"]


# Phrase: "write files directly under `--output` as `part-00000.csv`,
#          `part-00001.csv`, ... in exact order rows are emitted from sorted stream"
# Context: File naming (no field partitioning).
def test_shards_follow_the_sorted_stream_order(run, work):
    work.csv("a.csv", ["id"], [[str((i * 7) % 12)] for i in range(12)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "4",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    seen = []
    for name in ["part-00000.csv", "part-00001.csv", "part-00002.csv"]:
        seen += [int(row[0]) for row in read_csv_file(out / name)[1:]]
    assert seen == list(range(12))


# Phrase: "(zero-padded width 5)"
# Context: File naming.
def test_part_names_are_zero_padded_to_width_five(run, work):
    work.csv("a.csv", ["id"], [[str(i)] for i in range(3)])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "1",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]


# Phrase: "rows must be globally sorted by `--key`"
# Context: Sorting Guarantees with no field partitioning; sharding must not
# disturb the global order.
def test_global_order_preserved_across_shards(run, work):
    n = 200
    work.csv("a.csv", ["id"], [[str((i * 37) % n)] for i in range(n)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "17",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    seen = []
    for name in tree(out):
        seen += [int(row[0]) for row in read_csv_file(out / name)[1:]]
    assert seen == list(range(n))


# Phrase: "cut so on-disk byte size of each file (including header and line
#          endings) is <= INT"
# Context: Partitioning by Size or Rows.
def test_max_bytes_respected_on_disk(run, work):
    work.csv("a.csv", ["id", "pad"], [[str(i), "x" * 20] for i in range(40)])
    schema = work.schema("s.json", [("id", "int"), ("pad", "string")])
    out = work.path("out")
    limit = 120
    r = run("--output", out, "--key", "id", "--max-bytes-per-file", str(limit),
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    names = tree(out)
    assert len(names) > 1
    for name in names:
        assert part_size(out, name) <= limit, name


# Phrase: "including header and line endings"
# Context: the header counts inside every part, not just the first.
def test_header_counts_toward_the_byte_budget_of_each_part(run, work):
    # header "id\n" = 3 bytes; each row "NN\n" = 3 bytes. A 10-byte budget
    # therefore holds the header plus two rows (9 bytes), never three (12).
    work.csv("a.csv", ["id"], [[str(10 + i)] for i in range(6)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-bytes-per-file", "10",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    for name in tree(out):
        assert part_size(out, name) == 9


# Phrase: "Exception: if single row alone exceeds INT, place that row in file by
#          itself (allowed to exceed limit)"
# Context: Partitioning by Size or Rows.
def test_oversized_row_lands_in_a_file_by_itself(run, work):
    work.csv(
        "a.csv",
        ["id", "pad"],
        [["1", "a"], ["2", "b" * 500], ["3", "c"]],
    )
    schema = work.schema("s.json", [("id", "int"), ("pad", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-bytes-per-file", "40",
            "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    names = tree(out)
    contents = [read_csv_file(out / n)[1:] for n in names]
    big = [rows for rows in contents if any(len(c[1]) == 500 for c in rows)]
    assert len(big) == 1
    assert len(big[0]) == 1
    # every other part stayed within the limit
    for name, rows in zip(names, contents):
        if not any(len(c[1]) == 500 for c in rows):
            assert part_size(out, name) <= 40


# Phrase: "When both `--max-rows-per-file` and `--max-bytes-per-file` provided,
#          cut at earliest boundary that would violate either constraint"
# Context: the row limit binds first here.
def test_both_limits_rows_bind_first(run, work):
    work.csv("a.csv", ["id"], [[str(10 + i)] for i in range(6)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "2",
            "--max-bytes-per-file", "1000", "--schema", schema,
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert all(len(read_csv_file(out / n)) - 1 == 2 for n in tree(out))


# Phrase: "cut at earliest boundary that would violate either constraint"
# Context: the byte limit binds first here.
def test_both_limits_bytes_bind_first(run, work):
    work.csv("a.csv", ["id"], [[str(10 + i)] for i in range(6)])
    schema = work.schema("s.json", [("id", "int")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "1000",
            "--max-bytes-per-file", "10", "--schema", schema,
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    for name in tree(out):
        assert part_size(out, name) <= 10


# Phrase: "File naming (with field partitioning): same `part-xxxxx.csv` sequence
#          per partition directory"
# Context: numbering restarts inside every partition (AMBIGUITIES T42).
def test_part_numbering_restarts_in_each_partition(run, work):
    rows = []
    for i in range(12):
        rows.append([str(i), "g%d" % (i % 2)])
    work.csv("a.csv", ["id", "g"], rows)
    schema = work.schema("s.json", [("id", "int"), ("g", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--max-rows-per-file", "2", "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == [
        "g=g0/part-00000.csv", "g=g0/part-00001.csv", "g=g0/part-00002.csv",
        "g=g1/part-00000.csv", "g=g1/part-00001.csv", "g=g1/part-00002.csv",
    ]


# Phrase: "rows in each partition directory must be sorted by `--key` within
#          that partition"
# Context: sharded partitions concatenate back into sorted order.
def test_sharded_partitions_concatenate_to_sorted_order(run, work):
    n = 60
    rows = [[str((i * 23) % n), "g%d" % (i % 3)] for i in range(n)]
    work.csv("a.csv", ["id", "g"], rows)
    schema = work.schema("s.json", [("id", "int"), ("g", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--max-rows-per-file", "4", "--schema", schema, work.path("a.csv"))
    assert r.ok, r.stderr
    for group in ("g=g0", "g=g1", "g=g2"):
        names = sorted(p for p in tree(out) if p.startswith(group + "/"))
        seen = []
        for name in names:
            seen += [int(row[0]) for row in read_csv_file(out / name)[1:]]
        assert seen == sorted(seen)
        assert len(seen) == n // 3


# Phrase: "Continue to honor small `--memory-limit-mb` values"
# Context: Memory & External Merge; sharding runs off the external merge stream.
def test_sharding_under_small_memory_limit(run, work):
    n = 5000
    work.csv("a.csv", ["id", "pad"], [[str((i * 7919) % n), "y" * 10]
                                      for i in range(n)])
    schema = work.schema("s.json", [("id", "int"), ("pad", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "500",
            "--memory-limit-mb", "1", "--schema", schema, work.path("a.csv"),
            timeout=300)
    assert r.ok, r.stderr
    names = tree(out)
    assert len(names) == 10
    seen = []
    for name in names:
        seen += [int(row[0]) for row in read_csv_file(out / name)[1:]]
    assert seen == list(range(n))


# Phrase: "Tool must work on arbitrarily large inputs"
# Context: Memory & External Merge; many partitions must not exhaust file
# handles even though the sorted stream interleaves them.
def test_many_partitions_under_small_memory_limit(run, work):
    n = 2000
    rows = [[str(i), "g%04d" % (i % 400)] for i in range(n)]
    work.csv("a.csv", ["id", "g"], rows)
    schema = work.schema("s.json", [("id", "int"), ("g", "string")])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            "--memory-limit-mb", "1", "--schema", schema, work.path("a.csv"),
            timeout=300)
    assert r.ok, r.stderr
    names = tree(out)
    assert len(names) == 400
    total = sum(len(read_csv_file(out / name)) - 1 for name in names)
    assert total == n


# Phrase: "cut output into files with at most INT data rows each"
# Context: an exact multiple leaves no trailing empty part.
def test_exact_multiple_leaves_no_empty_trailing_part(run, work):
    work.csv("a.csv", ["id"], [[str(i)] for i in range(6)])
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "3",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]


# Phrase: "Every output CSV includes header row in resolved schema column order"
# Context: AMBIGUITIES T39 -- a sharded run with no data rows still names its
# single part file and writes the header.
def test_no_data_rows_still_writes_header_only_part(run, work):
    work.write("a.csv", "id,v\n")
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--max-rows-per-file", "5",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert tree(out) == ["part-00000.csv"]
    assert read_csv_file(out / "part-00000.csv") == [["id", "v"]]


# Phrase: "Rows for each unique combination of partition column values go into
#          separate directory"
# Context: AMBIGUITIES T39 -- no rows means no combinations, so no directories.
def test_no_data_rows_with_field_partitioning_makes_empty_dir(run, work):
    work.write("a.csv", "id,g\n")
    out = work.path("out")
    r = run("--output", out, "--key", "id", "--partition-by", "g",
            work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.is_dir()
    assert tree(out) == []


# Phrase: "--max-rows-per-file <INT>"
# Context: a non-positive limit is a usage error.
def test_zero_max_rows_is_a_usage_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", work.path("out"), "--key", "id",
            "--max-rows-per-file", "0", work.path("a.csv"))
    assert r.returncode == 2


def test_zero_max_bytes_is_a_usage_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", work.path("out"), "--key", "id",
            "--max-bytes-per-file", "0", work.path("a.csv"))
    assert r.returncode == 2
