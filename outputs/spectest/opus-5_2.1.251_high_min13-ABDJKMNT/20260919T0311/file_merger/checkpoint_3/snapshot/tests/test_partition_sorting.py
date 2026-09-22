"""Spec sections: Sorting Guarantees, CSV Output Contents, Memory & External
Merge, for partitioned output."""
import csv

from conftest import data_rows, lines, parts, tree


def _all_rows(root):
    """Every data row under `root`, partition by partition, part by part."""
    return [row for part in sorted(root.rglob("part-*.csv")) for row in data_rows(part)]


# Phrase: "With no field partitioning: rows must be globally sorted by --key
#   (and --desc if set)"
# Context: the shard sequence is one globally sorted stream.
def test_sharded_stream_is_globally_sorted(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n3\n1\n")
    csv_file("b.csv", "id\n4\n2\n")
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "1",
              "a.csv", "b.csv")
    assert res.returncode == 0, res.stderr
    assert [row[0] for p in parts(tmp_path / "out") for row in data_rows(p)] == \
        ["1", "2", "3", "4"]


# Phrase: "(and --desc if set)"
# Context: --desc reverses the globally sorted shard stream.
def test_sharded_stream_honours_desc(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n3\n1\n2\n")
    res = run("--output", "out", "--key", "id", "--desc",
              "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [row[0] for p in parts(tmp_path / "out") for row in data_rows(p)] == \
        ["3", "2", "1"]


# Phrase: "With field partitioning: rows in each partition directory must be
#   sorted by --key within that partition"
# Context: each partition is independently ordered.
def test_rows_are_sorted_within_each_partition(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n3,US\n1,FR\n2,US\n4,FR\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [r[1] for r in data_rows(tmp_path / "out" / "c=US" / "part-00000.csv")] == ["2", "3"]
    assert [r[1] for r in data_rows(tmp_path / "out" / "c=FR" / "part-00000.csv")] == ["1", "4"]


# Phrase: "rows in each partition directory must be sorted by --key within that
#   partition"
# Context: --desc applies inside every partition, and the key may be composite.
def test_partition_sorting_with_desc_and_composite_key(run, csv_file, tmp_path):
    csv_file("a.csv", "c,ts,id\nUS,2024-01-01,2\nUS,2024-01-01,1\nUS,2024-01-02,3\n")
    res = run("--output", "out", "--key", "ts,id", "--desc", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [r[1] for r in data_rows(tmp_path / "out" / "c=US" / "part-00000.csv")] == \
        ["3", "2", "1"]


# Phrase: "sorted by --key within that partition"
# Context: the ordering continues across the shards of one partition.
def test_partition_order_continues_across_its_shards(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n" + "".join(f"{i},US\n" for i in [4, 2, 5, 1, 3]))
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [r[1] for r in _all_rows(tmp_path / "out")] == ["1", "2", "3", "4", "5"]


# Phrase: "Every output CSV includes header row in resolved schema column order"
# Context: an explicit schema fixes the header of every part file.
def test_header_follows_the_resolved_schema_order(run, csv_file, schema_file, tmp_path):
    csv_file("a.csv", "c,id\nUS,1\n")
    schema = schema_file([("id", "int"), ("c", "string")])
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--schema", schema, "a.csv")
    assert res.returncode == 0, res.stderr
    assert lines((tmp_path / "out" / "c=US" / "part-00000.csv").read_text()) == ["id,c", "1,US"]


# Phrase: "Use same delimiter/quote/escape/line-ending/null-literal rules as
#   before"
# Context: quoting and the null literal behave exactly as in single-file output.
def test_output_dialect_matches_single_file_output(run, csv_file, tmp_path):
    csv_file("a.csv", 'id,v\n1,"a,b"\n2,"say ""hi"""\n3,\n')
    sharded = run("--output", "out", "--key", "id",
                  "--csv-null-literal", "NULL", "--max-rows-per-file", "10", "a.csv")
    assert sharded.returncode == 0, sharded.stderr
    single = run("--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv")
    assert (tmp_path / "out" / "part-00000.csv").read_text() == single.stdout


# Phrase: "Each partition file is independently valid CSV"
# Context: every file parses on its own, header plus its own rows.
def test_each_part_file_parses_standalone(run, csv_file, tmp_path):
    csv_file("a.csv", 'id,c\n1,"US, East"\n2,"US, East"\n3,FR\n')
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--max-rows-per-file", "1", "a.csv")
    assert res.returncode == 0, res.stderr
    for part in sorted((tmp_path / "out").rglob("part-*.csv")):
        with open(part, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == ["c", "id"]
        assert len(rows) == 2 and len(rows[1]) == 2


# Phrase: "Continue to honor small --memory-limit-mb values"
# Context: partitioned output still comes out right when the sort has spilled.
def test_partitioned_output_under_a_small_memory_limit(run, csv_file, tmp_path):
    rows = "".join(f"{i},c{i % 3}\n" for i in range(2000, 0, -1))
    csv_file("a.csv", "id,c\n" + rows)
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--memory-limit-mb", "1", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        "c=c0/part-00000.csv", "c=c1/part-00000.csv", "c=c2/part-00000.csv",
    ]
    ids = [int(r[1]) for r in data_rows(tmp_path / "out" / "c=c0" / "part-00000.csv")]
    assert ids == sorted(ids) and len(ids) == 666


# Phrase: "Tool must work on arbitrarily large inputs"
# Context: sharding a spilled sort keeps every row exactly once.
def test_sharded_output_under_a_small_memory_limit(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in range(3000, 0, -1)))
    res = run("--output", "out", "--key", "id", "--memory-limit-mb", "1",
              "--max-rows-per-file", "700", "a.csv")
    assert res.returncode == 0, res.stderr
    emitted = [int(r[0]) for p in parts(tmp_path / "out") for r in data_rows(p)]
    assert emitted == list(range(1, 3001))
