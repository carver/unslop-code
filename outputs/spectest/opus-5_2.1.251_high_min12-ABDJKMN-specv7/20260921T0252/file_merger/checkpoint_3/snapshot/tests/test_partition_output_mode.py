"""Spec section: Partitioned Output -> Output Location & Mode."""
import os

from conftest import (run_tool, write_csv, read_rows, part_files, read_text,
                      tree_files)


# Phrase: "When no partitioning flags provided: write single CSV to --output
#          (file path or - for stdout)"
# Context: the checkpoint-1 behaviour is untouched when no new flag is given.
def test_no_partitioning_flags_stdout_still_single_csv(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "2", "1"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id\n1\n2\n"


# Phrase: "When no partitioning flags provided: write single CSV to --output
#          (file path ...)"
# Context: a plain path stays a single regular file, not a directory.
def test_no_partitioning_flags_path_is_single_file(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "2", "1"])
    out = tmp_path / "merged.csv"
    res = run_tool("--output", out, "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert out.is_file()
    assert read_text(out) == "id\n1\n2\n"


# Phrase: "When any partitioning flag provided: --output must be directory
#          path (not -)"
# Context: --partition-by with --output - is rejected.
def test_partition_by_with_stdout_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    res = run_tool("--output", "-", "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 2, (res.returncode, res.stderr)
    assert res.stderr.strip() != ""


# Phrase: "When any partitioning flag provided: --output must be directory
#          path (not -)"
# Context: --max-rows-per-file alone also makes --output - illegal.
def test_max_rows_with_stdout_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--max-rows-per-file", "10", src)
    assert res.returncode == 2, (res.returncode, res.stderr)


# Phrase: "When any partitioning flag provided: --output must be directory
#          path (not -)"
# Context: --max-bytes-per-file alone also makes --output - illegal.
def test_max_bytes_with_stdout_rejected(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--max-bytes-per-file", "1000", src)
    assert res.returncode == 2, (res.returncode, res.stderr)


# Phrase: "--output must be directory path"
# Context: with a partitioning flag the output path becomes a directory.
def test_output_is_directory_under_partitioning(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "1", src)
    assert res.returncode == 0, res.stderr
    assert out.is_dir()


# Phrase: "Create directory if doesn't exist"
# Context: a missing output directory is created rather than being an error.
def test_missing_output_directory_created(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "does" / "not" / "exist"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "id", src)
    assert res.returncode == 0, res.stderr
    assert out.is_dir()


# Phrase: "Create directory if doesn't exist"
# Context: an already existing (empty) output directory is accepted.
def test_existing_output_directory_accepted(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "7"])
    out = tmp_path / "out"
    out.mkdir()
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "id", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["id=7/part-00000.csv"]


# Phrase: "Perform atomic write by creating sibling temp directory and
#          renaming on success"
# Context: on success no sibling temp directory is left behind.
def test_no_temp_siblings_left_on_success(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "id", src)
    assert res.returncode == 0, res.stderr
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["a.csv", "out"], siblings


# Phrase: "On failure, remove temp directory and partial files"
# Context: a cast failure mid-stream leaves no temp directory behind.
def test_failure_removes_temp_directory(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,v", "1,1", "2,oops"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "id",
                   "--schema", '{"columns":[{"name":"id","type":"int"},'
                               '{"name":"v","type":"int"}]}',
                   "--on-type-error", "fail", src)
    assert res.returncode != 0, res.stdout
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings in (["a.csv"], ["a.csv", "out"]), siblings
    # nothing partial may be visible inside the output directory
    assert tree_files(out) == []


# Phrase: "On failure, remove temp directory and partial files"
# Context: an unknown key column fails before anything is written.
def test_failure_leaves_no_part_files(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "nope",
                   "--partition-by", "c", src)
    assert res.returncode == 3, (res.returncode, res.stderr)
    assert tree_files(out) == []


# Phrase: "--output must be directory path"
# Context: nothing is written to stdout when output goes to a directory.
def test_directory_mode_writes_nothing_to_stdout(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "5", src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""


# Phrase: "--output must be directory path"
# Context: an existing regular file at the output path is an error, and the
# file is left untouched.
def test_output_path_is_regular_file_errors(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    out = tmp_path / "out"
    out.write_text("keep me\n", encoding="utf-8")
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "5", src)
    assert res.returncode != 0
    assert res.stderr.startswith("error: ")
    assert out.read_text(encoding="utf-8") == "keep me\n"
