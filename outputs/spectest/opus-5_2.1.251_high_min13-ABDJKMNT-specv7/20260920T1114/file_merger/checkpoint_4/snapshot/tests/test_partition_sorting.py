"""Spec sections: Sorting Guarantees, CSV Output Contents, Memory & External Merge."""

import csv
import io
import random

from conftest import read, rows_of, tree


def part_texts(directory) -> list[str]:
    """Contents of every part file under `directory`, in part-name order."""
    return [read(directory / name) for name in tree(directory)]


# Phrase: "With no field partitioning: rows must be globally sorted by --key"
# Context: Sorting Guarantees. The parts concatenate into one sorted stream.
def test_sharded_parts_are_globally_sorted(csv_file, run_tool, workdir):
    order = list(range(50))
    random.Random(7).shuffle(order)
    csv_file("a.csv", "id\n" + "".join(f"{value}\n" for value in order))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "7", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    emitted = [row[0] for text in part_texts(workdir / "out") for row in rows_of(text)]
    assert emitted == [str(value) for value in range(50)]


# Phrase: "(and --desc if set)"
# Context: Sorting Guarantees, no field partitioning.
def test_sharded_parts_honour_desc(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n1\n3\n2\n4\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--desc", "--max-rows-per-file", "2", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    emitted = [row[0] for text in part_texts(workdir / "out") for row in rows_of(text)]
    assert emitted == ["4", "3", "2", "1"]


# Phrase: "With field partitioning: rows in each partition directory must be sorted
#          by --key within that partition"
# Context: Sorting Guarantees.
def test_rows_are_sorted_within_each_partition(csv_file, run_tool, workdir):
    csv_file(
        "a.csv",
        "id,country\n3,US\n1,FR\n2,US\n5,FR\n1,US\n",
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    us = rows_of(read(workdir / "out/country=US/part-00000.csv"))
    fr = rows_of(read(workdir / "out/country=FR/part-00000.csv"))
    assert [row[1] for row in us] == ["1", "2", "3"]
    assert [row[1] for row in fr] == ["1", "5"]


# Phrase: "rows in each partition directory must be sorted by --key"
# Context: Sorting Guarantees. Sharded parts of a partition continue the order.
def test_partition_parts_continue_the_sorted_order(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n" + "".join(f"{i},US\n" for i in [4, 1, 3, 2]))
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--max-rows-per-file", "2", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    first = rows_of(read(workdir / "out/country=US/part-00000.csv"))
    second = rows_of(read(workdir / "out/country=US/part-00001.csv"))
    assert [row[1] for row in first] == ["1", "2"]
    assert [row[1] for row in second] == ["3", "4"]


# Phrase: "rows in each partition directory must be sorted by --key within that partition"
# Context: Sorting Guarantees, composite key and --desc together.
def test_partition_sorting_honours_composite_keys_and_desc(csv_file, run_tool, workdir):
    csv_file(
        "a.csv",
        "id,ts,country\n1,2024-01-01T00:00:00Z,US\n2,2024-01-02T00:00:00Z,US\n"
        "3,2024-01-02T00:00:00Z,US\n",
    )
    result = run_tool(
        "--output", "out", "--key", "ts,id", "--desc", "--partition-by", "country",
        "a.csv",
    )
    assert result.returncode == 0, result.stderr
    rows = rows_of(read(workdir / "out/country=US/part-00000.csv"))
    assert [row[1] for row in rows] == ["3", "2", "1"]


# Phrase: "Every output CSV includes header row in resolved schema column order"
# Context: CSV Output Contents.
def test_header_is_the_resolved_schema_order(csv_file, run_tool, workdir):
    csv_file("a.csv", "note,id,country\nhello,1,US\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"},'
        ' {"name": "country", "type": "string"}, {"name": "note", "type": "string"}]}',
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--schema", "schema.json",
        "--partition-by", "country", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    text = read(workdir / "out/country=US/part-00000.csv")
    assert text == "id,country,note\n1,US,hello\n"


# Phrase: "Use same delimiter/quote/escape/line-ending/null-literal rules as before"
# Context: CSV Output Contents. Quoting and the null literal apply to part files.
def test_part_files_use_the_configured_dialect(csv_file, run_tool, workdir):
    csv_file("a.csv", 'id,country,note\n1,US,"a,b"\n2,US,\n')
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--csv-null-literal", "NULL", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert read(workdir / "out/country=US/part-00000.csv") == (
        'country,id,note\nUS,1,"a,b"\nUS,2,NULL\n'
    )


# Phrase: "Each partition file is independently valid CSV"
# Context: CSV Output Contents. Each file parses on its own, header first.
def test_each_part_file_parses_independently(csv_file, run_tool, workdir):
    csv_file(
        "a.csv",
        'id,country,note\n1,US,"line\nbreak"\n2,US,plain\n3,FR,"quote""d"\n',
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--max-rows-per-file", "1", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    for name in tree(workdir / "out"):
        parsed = list(csv.reader(io.StringIO(read(workdir / "out" / name), newline="")))
        assert parsed[0] == ["country", "id", "note"]
        assert len(parsed) == 2
    first = rows_of(read(workdir / "out/country=US/part-00000.csv"))
    assert first[0][2] == "line\nbreak"


# Phrase: "Continue to honor small --memory-limit-mb values"
# Context: Memory & External Merge. Partitions survive spilling to disk.
def test_partitioning_works_under_a_small_memory_limit(csv_file, run_tool, workdir):
    order = list(range(4000))
    random.Random(11).shuffle(order)
    payload = "x" * 200
    csv_file(
        "a.csv",
        "id,bucket,payload\n"
        + "".join(f"{value},{value % 3},{payload}\n" for value in order),
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "bucket",
        "--memory-limit-mb", "1", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "bucket=0/part-00000.csv",
        "bucket=1/part-00000.csv",
        "bucket=2/part-00000.csv",
    ]
    total = 0
    for bucket in range(3):
        rows = rows_of(read(workdir / f"out/bucket={bucket}/part-00000.csv"))
        values = [int(row[1]) for row in rows]
        assert values == sorted(values)
        assert all(value % 3 == bucket for value in values)
        total += len(values)
    assert total == 4000


# Phrase: "Tool must work on arbitrarily large inputs"
# Context: Memory & External Merge. Sharding a spilled stream stays globally sorted.
def test_sharding_works_under_a_small_memory_limit(csv_file, run_tool, workdir):
    order = list(range(4000))
    random.Random(13).shuffle(order)
    payload = "x" * 200
    csv_file("a.csv", "id,payload\n" + "".join(f"{v},{payload}\n" for v in order))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "500",
        "--memory-limit-mb", "1", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    names = tree(workdir / "out")
    assert names[0] == "part-00000.csv" and len(names) == 8
    emitted = [
        int(row[0]) for name in names for row in rows_of(read(workdir / "out" / name))
    ]
    assert emitted == list(range(4000))
