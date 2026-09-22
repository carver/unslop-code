"""Spec section: Partitioned Output / Partitioning by Size or Rows (sharding)."""
from conftest import data_rows, lines, parts, tree


def _ids(path):
    return [row[0] for row in data_rows(path)]


# Phrase: "--max-rows-per-file <INT>: cut output into files with at most INT
#   data rows each (header not counted)"
# Context: the header does not consume any of the row budget.
def test_max_rows_counts_data_rows_only(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in range(5)))
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    files = parts(tmp_path / "out")
    assert [p.name for p in files] == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [_ids(p) for p in files] == [["0", "1"], ["2", "3"], ["4"]]


# Phrase: "cut output into files with at most INT data rows each"
# Context: a row count that divides exactly leaves no trailing empty file.
def test_exact_multiple_leaves_no_empty_trailing_file(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n1\n2\n3\n4\n")
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["part-00000.csv", "part-00001.csv"]


# Phrase: "--max-bytes-per-file <INT>: cut so on-disk byte size of each file
#   (including header and line endings) is ≤ INT"
# Context: the measured size is the file on disk, header included.
def test_max_bytes_limits_the_whole_file(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n" + "".join(f"{i},aaaa\n" for i in range(6)))
    # header "id,v\n" is 5 bytes and each row "N,aaaa\n" is 7, so 19 fits two rows.
    res = run("--output", "out", "--key", "id", "--max-bytes-per-file", "19", "a.csv")
    assert res.returncode == 0, res.stderr
    files = parts(tmp_path / "out")
    assert [p.stat().st_size for p in files] == [19, 19, 19]
    assert [_ids(p) for p in files] == [["0", "1"], ["2", "3"], ["4", "5"]]


# Phrase: "is ≤ INT"
# Context: no file exceeds the limit when every row fits inside it.
def test_no_file_exceeds_the_byte_limit(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n" + "".join(f"{i},value{i}\n" for i in range(40)))
    res = run("--output", "out", "--key", "id", "--max-bytes-per-file", "40", "a.csv")
    assert res.returncode == 0, res.stderr
    assert all(p.stat().st_size <= 40 for p in parts(tmp_path / "out"))


# Phrase: "Exception: if single row alone exceeds INT, place that row in file by
#   itself (allowed to exceed limit)"
# Context: T42 - the header comes with it, and the run does not loop forever.
def test_oversized_row_gets_its_own_file(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n1,aaaaaaaaaa\n2,b\n")
    res = run("--output", "out", "--key", "id", "--max-bytes-per-file", "8", "a.csv")
    assert res.returncode == 0, res.stderr
    files = parts(tmp_path / "out")
    assert [_ids(p) for p in files] == [["1"], ["2"]]
    assert lines(files[0].read_text()) == ["id,v", "1,aaaaaaaaaa"]


# Phrase: "When both --max-rows-per-file and --max-bytes-per-file provided, cut
#   at earliest boundary that would violate either constraint"
# Context: the byte limit bites first here, before the row limit does.
def test_byte_limit_can_cut_before_the_row_limit(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n" + "".join(f"{i},aaaa\n" for i in range(6)))
    res = run("--output", "out", "--key", "id",
              "--max-rows-per-file", "10", "--max-bytes-per-file", "19", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [_ids(p) for p in parts(tmp_path / "out")] == [["0", "1"], ["2", "3"], ["4", "5"]]


# Phrase: "cut at earliest boundary that would violate either constraint"
# Context: the row limit bites first here, before the byte limit does.
def test_row_limit_can_cut_before_the_byte_limit(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n" + "".join(f"{i},aaaa\n" for i in range(6)))
    res = run("--output", "out", "--key", "id",
              "--max-rows-per-file", "2", "--max-bytes-per-file", "1000", "a.csv")
    assert res.returncode == 0, res.stderr
    assert [_ids(p) for p in parts(tmp_path / "out")] == [["0", "1"], ["2", "3"], ["4", "5"]]


# Phrase: "File naming (no field partitioning): write files directly under
#   --output as part-00000.csv, part-00001.csv, …"
# Context: no partition directories appear when only sharding is asked for.
def test_shards_sit_directly_under_output(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n1\n2\n3\n")
    run("--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv")
    assert tree(tmp_path / "out") == [
        "part-00000.csv", "part-00001.csv", "part-00002.csv",
    ]


# Phrase: "in exact order rows are emitted from sorted stream"
# Context: concatenating the shards in name order rebuilds the global ordering.
def test_shards_follow_the_sorted_stream_order(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in [5, 3, 9, 1, 7, 2]))
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    emitted = [row[0] for p in parts(tmp_path / "out") for row in data_rows(p)]
    assert emitted == ["1", "2", "3", "5", "7", "9"]


# Phrase: "File naming (with field partitioning): same part-xxxxx.csv sequence
#   per partition directory"
# Context: cutting rules apply inside each partition independently.
def test_cutting_applies_within_each_partition(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n2,US\n3,US\n4,FR\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    # Inferred column order is lexicographic, so the row is (c, id).
    assert [[r[1] for r in data_rows(p)] for p in parts(tmp_path / "out" / "c=US")] == \
        [["1", "2"], ["3"]]
    assert [[r[1] for r in data_rows(p)] for p in parts(tmp_path / "out" / "c=FR")] == [["4"]]


# Phrase: "part-00000.csv, part-00001.csv, … (zero-padded width 5)"
# Context: the counter keeps its five-digit padding as it climbs.
def test_part_names_are_zero_padded_to_five_digits(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n" + "".join(f"{i}\n" for i in range(12)))
    run("--output", "out", "--key", "id", "--max-rows-per-file", "1", "a.csv")
    names = [p.name for p in parts(tmp_path / "out")]
    assert names[0] == "part-00000.csv" and names[11] == "part-00011.csv"


# Phrase: "--max-rows-per-file <INT>"
# Context: T46 - a non-positive limit cannot describe a file, so it is a usage
#   error rather than an infinite sequence of empty files.
def test_non_positive_limits_are_usage_errors(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    assert run("--output", "out", "--key", "id", "--max-rows-per-file", "0",
               "a.csv").returncode == 2
    assert run("--output", "out", "--key", "id", "--max-bytes-per-file", "0",
               "a.csv").returncode == 2


# Phrase: "Size/row-based cutting produces deterministically named
#   part-xxxxx.csv files with headers"
# Context: T40 - sharding an empty stream still yields one headed file.
def test_empty_stream_still_writes_one_headed_part(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n")
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "10", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["part-00000.csv"]
    assert lines((tmp_path / "out" / "part-00000.csv").read_text()) == ["id,v"]
