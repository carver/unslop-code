"""Spec section: Partitioning by Size or Rows — cutting rules and part naming."""

from conftest import read, rows_of, tree


def ids(text: str) -> list[str]:
    """The `id` column of one part file, in file order."""
    return [row[0] for row in rows_of(text)]


# Phrase: "--max-rows-per-file <INT>: cut output into files with at most INT data rows"
# Context: Partitioning by Size or Rows.
def test_rows_are_cut_at_the_row_limit(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in range(5)))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "part-00000.csv",
        "part-00001.csv",
        "part-00002.csv",
    ]
    assert ids(read(workdir / "out/part-00000.csv")) == ["0", "1"]
    assert ids(read(workdir / "out/part-00001.csv")) == ["2", "3"]
    assert ids(read(workdir / "out/part-00002.csv")) == ["4"]


# Phrase: "at most INT data rows each (header not counted)"
# Context: Partitioning by Size or Rows. A limit of 1 gives one data row per file.
def test_header_does_not_count_towards_the_row_limit(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n1\n2\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert read(workdir / "out/part-00000.csv") == "id\n1\n"
    assert read(workdir / "out/part-00001.csv") == "id\n2\n"


# Phrase: "--max-rows-per-file"
# Context: Partitioning by Size or Rows. A limit above the row count gives one file.
def test_row_limit_larger_than_the_input_gives_one_file(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n1\n2\n3\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "100", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv"]


# Phrase: "--max-bytes-per-file <INT>: cut so on-disk byte size of each file
#          (including header and line endings) is ≤ INT"
# Context: Partitioning by Size or Rows.
def test_files_stay_within_the_byte_limit(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,payload\n" + "".join(f"{i},xxx\n" for i in range(6)))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "24", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    names = tree(workdir / "out")
    assert names == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    for name in names:
        assert (workdir / "out" / name).stat().st_size <= 24
    assert read(workdir / "out/part-00000.csv") == "id,payload\n0,xxx\n1,xxx\n"


# Phrase: "cut so on-disk byte size ... is ≤ INT"
# Context: Partitioning by Size or Rows. Cuts are made as late as the limit allows.
def test_byte_limit_packs_files_up_to_the_limit(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,payload\n" + "".join(f"{i},xxx\n" for i in range(6)))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "29", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv", "part-00001.csv"]
    assert read(workdir / "out/part-00000.csv") == "id,payload\n0,xxx\n1,xxx\n2,xxx\n"


# Phrase: "on-disk byte size ... (including header and line endings)"
# Context: Partitioning by Size or Rows. Ambiguity T46: bytes are UTF-8 bytes.
def test_byte_limit_counts_utf8_bytes(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,name\n1,éé\n2,éé\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "19", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv", "part-00001.csv"]
    assert (workdir / "out/part-00000.csv").stat().st_size == 15


# Phrase: "Exception: if single row alone exceeds INT, place that row in file by itself
#          (allowed to exceed limit)"
# Context: Partitioning by Size or Rows.
def test_oversized_row_gets_a_file_of_its_own(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,payload\n1,x\n2," + "y" * 100 + "\n3,z\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "20", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "part-00000.csv",
        "part-00001.csv",
        "part-00002.csv",
    ]
    assert ids(read(workdir / "out/part-00000.csv")) == ["1"]
    assert ids(read(workdir / "out/part-00001.csv")) == ["2"]
    assert ids(read(workdir / "out/part-00002.csv")) == ["3"]
    assert (workdir / "out/part-00001.csv").stat().st_size > 20


# Phrase: "When both --max-rows-per-file and --max-bytes-per-file provided, cut at
#          earliest boundary that would violate either constraint"
# Context: Partitioning by Size or Rows. Here the byte limit bites first.
def test_byte_limit_wins_when_it_is_the_earlier_boundary(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,payload\n" + "".join(f"{i},xxx\n" for i in range(6)))
    result = run_tool(
        "--output", "out", "--key", "id",
        "--max-rows-per-file", "5", "--max-bytes-per-file", "24", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert ids(read(workdir / "out/part-00000.csv")) == ["0", "1"]
    assert len(tree(workdir / "out")) == 3


# Phrase: "cut at earliest boundary that would violate either constraint"
# Context: Partitioning by Size or Rows. Here the row limit bites first.
def test_row_limit_wins_when_it_is_the_earlier_boundary(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,payload\n" + "".join(f"{i},xxx\n" for i in range(6)))
    result = run_tool(
        "--output", "out", "--key", "id",
        "--max-rows-per-file", "2", "--max-bytes-per-file", "1000", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert ids(read(workdir / "out/part-00000.csv")) == ["0", "1"]
    assert len(tree(workdir / "out")) == 3


# Phrase: "write files directly under --output as part-00000.csv, part-00001.csv, …
#          in exact order rows are emitted from sorted stream"
# Context: Partitioning by Size or Rows, no field partitioning.
def test_parts_follow_the_sorted_stream_order(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n5\n3\n1\n")
    csv_file("b.csv", "id\n4\n2\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "2",
        "a.csv", "b.csv",
    )
    assert result.returncode == 0, result.stderr
    assert ids(read(workdir / "out/part-00000.csv")) == ["1", "2"]
    assert ids(read(workdir / "out/part-00001.csv")) == ["3", "4"]
    assert ids(read(workdir / "out/part-00002.csv")) == ["5"]


# Phrase: "File naming (with field partitioning): same part-xxxxx.csv sequence per
#          partition directory"
# Context: Partitioning by Size or Rows. Ambiguity T43: numbering restarts per directory.
def test_part_numbering_restarts_in_each_partition(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n2,US\n3,FR\n4,FR\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--max-rows-per-file", "1", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=FR/part-00000.csv",
        "country=FR/part-00001.csv",
        "country=US/part-00000.csv",
        "country=US/part-00001.csv",
    ]


# Phrase: "Must respect size/row-based cutting rules if set"
# Context: Partitioning by Size or Rows. Byte cutting applies inside partitions too.
def test_byte_cutting_applies_within_a_partition(csv_file, run_tool, workdir):
    rows = "".join(f"{i},US\n" for i in range(4))
    csv_file("a.csv", "id,country\n" + rows)
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country",
        "--max-bytes-per-file", "20", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    for name in tree(workdir / "out"):
        assert (workdir / "out" / name).stat().st_size <= 20
    assert len(tree(workdir / "out")) > 1


# Phrase: "part-00000.csv, part-00001.csv, … (zero-padded width 5)"
# Context: Partitioning by Size or Rows. The sequence keeps counting past nine.
def test_part_sequence_continues_past_the_first_ten(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in range(12)))
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out")[-1] == "part-00011.csv"
    assert ids(read(workdir / "out/part-00011.csv")) == ["11"]
