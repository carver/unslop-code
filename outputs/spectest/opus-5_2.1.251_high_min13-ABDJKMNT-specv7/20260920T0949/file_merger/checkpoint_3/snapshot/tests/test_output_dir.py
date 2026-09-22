"""Where partitioned output lands: directory mode, creation, atomic rename."""

from conftest import rows_of


# Spec: "When no partitioning flags provided: write single CSV to `--output`
# (file path or `-` for stdout)"
def test_without_partitioning_flags_output_is_a_single_csv_file(make_csv, run, workdir):
    make_csv("a.csv", "id\n2\n1\n")
    run("--output", "out.csv", "--key", "id", "a.csv")
    assert (workdir / "out.csv").is_file()
    assert rows_of((workdir / "out.csv").read_text()) == [["id"], ["1"], ["2"]]


# Spec: "When no partitioning flags provided: write single CSV to ... `-` for stdout"
def test_without_partitioning_flags_dash_still_writes_stdout(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    assert run("--output", "-", "--key", "id", "a.csv").stdout == "id\n7\n"


# Spec: "When any partitioning flag provided: `--output` must be directory path"
# Context: --partition-by alone puts the tool into directory mode.
def test_partition_by_makes_output_a_directory(make_csv, run, workdir):
    make_csv("a.csv", "id,g\n1,x\n")
    run("--output", "out", "--key", "id", "--partition-by", "g", "a.csv")
    assert (workdir / "out").is_dir()


# Spec: "When any partitioning flag provided: `--output` must be directory path"
# Context: --max-rows-per-file alone also puts the tool into directory mode.
def test_max_rows_makes_output_a_directory(make_csv, run, workdir):
    make_csv("a.csv", "id\n1\n")
    run("--output", "out", "--key", "id", "--max-rows-per-file", "5", "a.csv")
    assert (workdir / "out").is_dir()


# Spec: "When any partitioning flag provided: `--output` must be directory path"
# Context: --max-bytes-per-file alone also puts the tool into directory mode.
def test_max_bytes_makes_output_a_directory(make_csv, run, workdir):
    make_csv("a.csv", "id\n1\n")
    run("--output", "out", "--key", "id", "--max-bytes-per-file", "500", "a.csv")
    assert (workdir / "out").is_dir()


# Spec: "`--output` must be directory path (not `-`)"
def test_dash_output_is_rejected_with_a_partitioning_flag(make_csv, run):
    make_csv("a.csv", "id,g\n1,x\n")
    proc = run("--output", "-", "--key", "id", "--partition-by", "g", "a.csv", expect_ok=False)
    assert proc.returncode == 2
    assert "--output" in proc.stderr


# Spec: "Create directory if doesn't exist"
def test_output_directory_is_created_including_parents(make_csv, run, workdir):
    make_csv("a.csv", "id,g\n1,x\n")
    run("--output", "nested/out", "--key", "id", "--partition-by", "g", "a.csv")
    assert (workdir / "nested/out/g=x/part-00000.csv").is_file()


# Spec: "Perform atomic write by creating sibling temp directory and renaming on success"
# Context: once the run succeeds only the output directory is left behind.
def test_successful_run_leaves_no_temp_siblings(make_csv, run, workdir):
    make_csv("a.csv", "id,g\n1,x\n2,y\n")
    run("--output", "out", "--key", "id", "--partition-by", "g", "a.csv")
    assert sorted(p.name for p in workdir.iterdir()) == ["a.csv", "out"]


# Spec: "On failure, remove temp directory and partial files"
def test_failed_run_leaves_neither_output_nor_temp_directory(make_csv, make_schema, run, workdir):
    make_csv("a.csv", "id,g\n1,x\nnope,y\n")
    make_schema("s.json", [("id", "int"), ("g", "string")])
    proc = run(
        "--output", "out", "--key", "g", "--partition-by", "g",
        "--schema", "s.json", "--on-type-error", "fail", "a.csv",
        expect_ok=False,
    )
    assert proc.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["a.csv", "s.json"]


# Spec: "Perform atomic write by creating sibling temp directory and renaming on success"
# Context: a second run over the same destination replaces the earlier tree (AMBIGUITIES T38).
def test_rerun_replaces_the_previous_tree(make_csv, run, tree):
    make_csv("a.csv", "id,g\n1,x\n")
    run("--output", "out", "--key", "id", "--partition-by", "g", "a.csv")
    make_csv("b.csv", "id,g\n2,y\n")
    run("--output", "out", "--key", "id", "--partition-by", "g", "b.csv")
    assert tree("out") == ["g=y/part-00000.csv"]
