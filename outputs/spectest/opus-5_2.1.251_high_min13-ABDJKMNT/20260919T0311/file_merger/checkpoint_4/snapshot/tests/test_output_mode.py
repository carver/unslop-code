"""Spec section: Partitioned Output / Output Location & Mode."""
from conftest import lines, table, tree


# Phrase: "When no partitioning flags provided: write single CSV to --output
#   (file path or - for stdout)"
# Context: the checkpoint-1 behaviour is unchanged when nothing is partitioned.
def test_no_partitioning_flags_writes_one_csv_file(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n2,b\n1,a\n")
    res = run("--output", "merged.csv", "--key", "id", "a.csv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "merged.csv").is_file()
    assert lines((tmp_path / "merged.csv").read_text()) == ["id,v", "1,a", "2,b"]


# Phrase: "file path or `-` for stdout"
# Context: stdout stays available while no partitioning flag is given.
def test_no_partitioning_flags_still_writes_stdout(run, csv_file):
    csv_file("a.csv", "id,v\n2,b\n1,a\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [["id", "v"], ["1", "a"], ["2", "b"]]


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: --partition-by makes the destination a directory tree.
def test_partition_by_writes_a_directory(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n2,FR\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "out").is_dir()
    assert tree(tmp_path / "out") == ["c=FR/part-00000.csv", "c=US/part-00000.csv"]


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: --max-rows-per-file alone is also a partitioning flag.
def test_max_rows_alone_writes_a_directory(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n1\n2\n3\n")
    res = run("--output", "out", "--key", "id", "--max-rows-per-file", "2", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["part-00000.csv", "part-00001.csv"]


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: --max-bytes-per-file alone is also a partitioning flag.
def test_max_bytes_alone_writes_a_directory(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n1\n2\n")
    res = run("--output", "out", "--key", "id", "--max-bytes-per-file", "1000", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["part-00000.csv"]


# Phrase: "--output must be directory path (not `-`)"
# Context: T38 - every partitioning flag rejects stdout as a usage error (exit 2).
def test_stdout_output_is_rejected_when_partitioning(run, csv_file):
    csv_file("a.csv", "id,c\n1,US\n")
    for flag, value in (("--partition-by", "c"),
                        ("--max-rows-per-file", "10"),
                        ("--max-bytes-per-file", "10")):
        res = run("--output", "-", "--key", "id", flag, value, "a.csv")
        assert res.returncode == 2, (flag, res.stdout, res.stderr)
        assert res.stderr.strip() != ""


# Phrase: "Create directory if doesn't exist"
# Context: missing intermediate levels of the --output path are created too.
def test_output_directory_is_created(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n")
    res = run("--output", "nested/out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "nested" / "out" / "c=US" / "part-00000.csv").is_file()


# Phrase: "Create directory if doesn't exist"
# Context: an existing (and empty) output directory is used as it is.
def test_existing_output_directory_is_accepted(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n")
    (tmp_path / "out").mkdir()
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["c=US/part-00000.csv"]


# Phrase: "Perform atomic write by creating sibling temp directory and renaming
#   on success"
# Context: T37 - the destination ends up holding exactly this run's tree, so a
#   stale part file from an earlier run is gone.
def test_rerun_replaces_previous_contents(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n")
    (tmp_path / "out" / "c=ZZ").mkdir(parents=True)
    (tmp_path / "out" / "c=ZZ" / "part-00000.csv").write_text("id,c\n9,ZZ\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["c=US/part-00000.csv"]


# Phrase: "Perform atomic write by creating sibling temp directory and renaming
#   on success"
# Context: nothing but the finished tree is left beside the destination.
def test_no_temporary_directory_survives_success(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n")
    run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv", "out"]


# Phrase: "On failure, remove temp directory and partial files"
# Context: a run that fails leaves neither the destination nor a temp sibling.
def test_failed_run_leaves_no_artifacts(run, csv_file, schema_file, tmp_path):
    csv_file("a.csv", "id,c\nnope,US\n")
    schema = schema_file([("id", "int"), ("c", "string")])
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode != 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv", "schema.json"]


# Phrase: "--output must be directory path"
# Context: T44 - pointing --output at an existing plain file is an error, not an
#   overwrite.
def test_existing_file_as_output_directory_fails(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n1,US\n")
    (tmp_path / "out").write_text("not a directory\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert res.returncode != 0
    assert (tmp_path / "out").read_text() == "not a directory\n"
