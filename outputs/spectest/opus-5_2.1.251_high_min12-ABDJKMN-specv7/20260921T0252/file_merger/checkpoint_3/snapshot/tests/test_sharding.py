"""Spec section: Partitioned Output -> Partitioning by Size or Rows."""
import os

from conftest import (run_tool, write_csv, read_rows, read_text, part_files,
                      tree_files, concat_body, col)


# Phrase: "--max-rows-per-file <INT>: cut output into files with at most INT
#          data rows each"
# Context: an exact multiple of the limit.
def test_exact_multiple_of_row_limit(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(6)])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "3", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]
    assert len(read_rows(out / "part-00000.csv")) == 4  # header + 3


# Phrase: "cut output into files with at most INT data rows each"
# Context: a remainder smaller than the limit forms the last file.
def test_row_limit_with_remainder(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(7)])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--max-rows-per-file", "3", src)
    counts = [len(read_rows(out / n)) - 1 for n in part_files(out)]
    assert counts == [3, 3, 1]


# Phrase: "(header not counted)"
# Context: with a limit of 1 each file holds exactly one data row plus header.
def test_header_not_counted_towards_row_limit(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--max-rows-per-file", "1", src)
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]
    assert read_text(out / "part-00000.csv") == "id\n1\n"
    assert read_text(out / "part-00001.csv") == "id\n2\n"


# Phrase: "--max-bytes-per-file <INT>: cut so on-disk byte size of each file
#          (including header and line endings) is <= INT"
# Context: no produced file may exceed the byte budget.
def test_no_file_exceeds_byte_limit(tmp_path):
    lines = ["id,name"] + ["%d,value%03d" % (i, i) for i in range(40)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "64", src)
    assert res.returncode == 0, res.stderr
    for name in part_files(out):
        assert os.path.getsize(str(out / name)) <= 64, name


# Phrase: "on-disk byte size of each file (including header and line endings)
#          is <= INT"
# Context: the header bytes count against the budget of every file.
def test_header_counts_towards_byte_limit(tmp_path):
    # header "id\n" = 3 bytes, each row "N\n" = 2 bytes.
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2", "3"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "7", src)
    assert res.returncode == 0, res.stderr
    assert read_text(out / "part-00000.csv") == "id\n1\n2\n"
    assert read_text(out / "part-00001.csv") == "id\n3\n"


# Phrase: "cut so on-disk byte size ... is <= INT"
# Context: packing is greedy -- a file is filled until the next row would
# break the limit.
def test_byte_packing_is_greedy(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2", "3", "4"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "9", src)
    assert res.returncode == 0, res.stderr
    assert read_text(out / "part-00000.csv") == "id\n1\n2\n3\n"
    assert read_text(out / "part-00001.csv") == "id\n4\n"


# Phrase: "Exception: if single row alone exceeds INT, place that row in file
#          by itself (allowed to exceed limit)"
# Context: an oversized row still gets written, alone.
def test_oversized_row_alone_in_its_file(tmp_path):
    big = "x" * 200
    src = write_csv(tmp_path / "a.csv", ["id,v", "1,a", "2," + big, "3,b"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "20", src)
    assert res.returncode == 0, res.stderr
    bodies = [read_rows(out / n)[1:] for n in part_files(out)]
    assert [len(b) for b in bodies] == [1, 1, 1]
    assert bodies[1] == [["2", big]]
    assert os.path.getsize(str(out / "part-00001.csv")) > 20


# Phrase: "if single row alone exceeds INT, place that row in file by itself"
# Context: the row after an oversized row starts a fresh file.
def test_row_after_oversized_row_starts_new_file(tmp_path):
    big = "y" * 100
    src = write_csv(tmp_path / "a.csv", ["id,v", "1," + big, "2,b", "3,c"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "16", src)
    assert res.returncode == 0, res.stderr
    assert read_rows(out / "part-00000.csv")[1:] == [["1", big]]
    assert read_rows(out / "part-00001.csv")[1:][0] == ["2", "b"]


# Phrase: "When both --max-rows-per-file and --max-bytes-per-file provided,
#          cut at earliest boundary that would violate either constraint"
# Context: the row limit bites first.
def test_both_limits_row_limit_wins(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(6)])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "2",
                   "--max-bytes-per-file", "1000", src)
    assert res.returncode == 0, res.stderr
    assert [len(read_rows(out / n)) - 1 for n in part_files(out)] == [2, 2, 2]


# Phrase: "cut at earliest boundary that would violate either constraint"
# Context: the byte limit bites first.
def test_both_limits_byte_limit_wins(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(6)])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "1000",
                   "--max-bytes-per-file", "7", src)
    assert res.returncode == 0, res.stderr
    assert [len(read_rows(out / n)) - 1 for n in part_files(out)] == [2, 2, 2]


# Phrase: "File naming (no field partitioning): write files directly under
#          --output as part-00000.csv, part-00001.csv, ..."
# Context: no subdirectories are created when only sharding is requested.
def test_shard_files_directly_under_output(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2", "3"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "2", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["part-00000.csv", "part-00001.csv"]


# Phrase: "part-00000.csv, part-00001.csv, ... (zero-padded width 5)"
# Context: indices past nine are still zero-padded to five digits.
def test_zero_padded_width_five(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(12)])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--max-rows-per-file", "1", src)
    names = part_files(out)
    assert names[0] == "part-00000.csv"
    assert names[10] == "part-00010.csv"
    assert len(names) == 12


# Phrase: "in exact order rows are emitted from sorted stream"
# Context: concatenating part files in name order rebuilds the sorted stream.
def test_parts_concatenate_to_sorted_stream(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "5", "1", "9"])
    b = write_csv(tmp_path / "b.csv", ["id", "3", "7"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "2", a, b)
    assert res.returncode == 0, res.stderr
    assert [r[0] for r in concat_body(out)] == ["1", "3", "5", "7", "9"]


# Phrase: "Each file contains header row"
# Context: every shard file repeats the header.
def test_every_shard_has_header(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a", "2,b", "3,c"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--max-rows-per-file", "1", src)
    for name in part_files(out):
        assert read_rows(out / name)[0] == ["id", "name"]


# Phrase: "File naming (with field partitioning): same part-xxxxx.csv sequence
#          per partition directory"
# Context: both flags together shard inside each Hive directory.
def test_sharding_inside_partition_directories(tmp_path):
    lines = ["id,c"] + ["%d,%s" % (i, "us" if i < 3 else "de")
                        for i in range(6)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "2", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == [
        "c=de/part-00000.csv", "c=de/part-00001.csv",
        "c=us/part-00000.csv", "c=us/part-00001.csv",
    ]


# Phrase: "--max-rows-per-file <INT>"
# Context: a non-positive row limit is a usage error.
def test_zero_row_limit_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "0", src)
    assert res.returncode == 2, (res.returncode, res.stderr)


# Phrase: "--max-bytes-per-file <INT>"
# Context: a non-positive byte limit is a usage error.
def test_zero_byte_limit_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "0", src)
    assert res.returncode == 2, (res.returncode, res.stderr)


# Phrase: "cut so on-disk byte size of each file ... is <= INT"
# Context: quoted fields are measured as written, not as the raw value.
def test_byte_accounting_uses_written_bytes(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,v', '1,"a,b"', '2,"c,d"'])
    out = tmp_path / "out"
    # header "id,v\n" = 5 bytes; each row '1,"a,b"\n' = 8 bytes.
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "13", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]
    assert os.path.getsize(str(out / "part-00000.csv")) == 13


# Phrase: "cut so on-disk byte size ... is <= INT"
# Context: multi-byte UTF-8 characters are counted in bytes, not characters.
def test_byte_accounting_counts_utf8_bytes(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,v", "1,ééé", "2,ééé"])
    out = tmp_path / "out"
    # header "id,v\n"=5, each row "1,ééé\n" = 1+1+6+1 = 9 bytes.
    res = run_tool("--output", out, "--key", "id",
                   "--max-bytes-per-file", "20", src)
    assert res.returncode == 0, res.stderr
    assert part_files(out) == ["part-00000.csv", "part-00001.csv"]
