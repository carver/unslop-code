"""Spec section: Output Location & Mode — directory mode, creation, atomicity."""

from conftest import leftovers, read, tree


# Phrase: "When no partitioning flags provided: write single CSV to --output (file path)"
# Context: Output Location & Mode. The single-file behaviour is unchanged.
def test_without_partitioning_flags_output_is_a_single_csv(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n2\n1\n")
    result = run_tool("--output", "merged.csv", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert read(workdir / "merged.csv") == "id\n1\n2\n"


# Phrase: "or - for stdout"
# Context: Output Location & Mode, with no partitioning flags.
def test_without_partitioning_flags_dash_still_writes_stdout(csv_file, run_tool):
    csv_file("a.csv", "id\n2\n1\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.stdout == "id\n1\n2\n"


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: Output Location & Mode. --partition-by makes --output a directory.
def test_partition_by_makes_the_output_a_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "out").is_dir()
    assert tree(workdir / "out") == ["country=US/part-00000.csv"]


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: Output Location & Mode. --max-rows-per-file alone is a partitioning flag.
def test_max_rows_alone_makes_the_output_a_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n2\n1\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "10", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv"]


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: Output Location & Mode. --max-bytes-per-file alone is a partitioning flag.
def test_max_bytes_alone_makes_the_output_a_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n2\n1\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "1000", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv"]


# Phrase: "--output must be directory path (not -)"
# Context: Output Location & Mode. Ambiguity T42: stdout with partitioning is misuse.
def test_dash_output_with_partitioning_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id,country\n1,US\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 2
    assert result.stderr.startswith("merge_files.py: error: ")
    assert result.stdout == ""


# Phrase: "--output must be directory path"
# Context: Output Location & Mode. Ambiguity T42: an existing file cannot be it.
def test_existing_file_as_partitioned_output_is_an_error(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n")
    csv_file("out", "not a directory\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 1
    assert result.stderr.startswith("merge_files.py: error: ")
    assert read(workdir / "out") == "not a directory\n"


# Phrase: "Create directory if doesn't exist"
# Context: Output Location & Mode. Missing parents are created too.
def test_output_directory_is_created_including_parents(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n")
    result = run_tool(
        "--output", "nested/out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "nested/out") == ["country=US/part-00000.csv"]


# Phrase: "Create directory if doesn't exist"
# Context: Output Location & Mode. An existing empty directory is reused.
def test_existing_empty_output_directory_is_used(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n")
    (workdir / "out").mkdir()
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["country=US/part-00000.csv"]


# Phrase: "Perform atomic write by creating sibling temp directory and renaming on success"
# Context: Output Location & Mode. Nothing of the staging area survives success.
def test_no_staging_directory_survives_a_successful_run(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\n2,FR\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert leftovers(workdir) == []
    assert sorted(entry.name for entry in workdir.iterdir()) == ["a.csv", "out"]


# Phrase: "On failure, remove temp directory and partial files"
# Context: Output Location & Mode. A cast failure leaves no output behind.
def test_failure_leaves_no_output_or_temp_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n1,US\nnope,FR\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "country", "type": "string"},'
        ' {"name": "id", "type": "int"}]}',
    )
    result = run_tool(
        "--output", "out", "--key", "id",
        "--schema", "schema.json", "--on-type-error", "fail",
        "--partition-by", "country", "a.csv",
    )
    assert result.returncode == 4
    assert not (workdir / "out").exists()
    assert leftovers(workdir) == []


# Phrase: "On failure, remove temp directory and partial files"
# Context: Output Location & Mode. Ambiguity T39: an existing tree is untouched.
def test_failure_leaves_an_existing_output_directory_untouched(
    csv_file, run_tool, workdir
):
    csv_file("a.csv", "id,country\nnope,US\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "country", "type": "string"},'
        ' {"name": "id", "type": "int"}]}',
    )
    (workdir / "out").mkdir()
    (workdir / "out" / "keep.txt").write_text("kept\n", encoding="utf-8")
    result = run_tool(
        "--output", "out", "--key", "id",
        "--schema", "schema.json", "--on-type-error", "fail",
        "--partition-by", "country", "a.csv",
    )
    assert result.returncode == 4
    assert tree(workdir / "out") == ["keep.txt"]
    assert leftovers(workdir) == []


# Phrase: "--partition-by <col>[,<col>...]"
# Context: Usage. A partition column outside the resolved schema is an error.
def test_unknown_partition_column_is_rejected(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 3
    assert result.stderr.startswith("merge_files.py: error: ")
    assert not (workdir / "out").exists()


# Phrase: "--max-rows-per-file <INT>"
# Context: Usage. Ambiguity T46: a non-positive limit is command-line misuse.
def test_zero_max_rows_per_file_is_misuse(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-rows-per-file", "0", "a.csv"
    )
    assert result.returncode == 2
    assert result.stderr


# Phrase: "--max-bytes-per-file <INT>"
# Context: Usage. Ambiguity T46: a negative limit is command-line misuse.
def test_negative_max_bytes_per_file_is_misuse(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--max-bytes-per-file", "-5", "a.csv"
    )
    assert result.returncode == 2
    assert result.stderr


# Phrase: "write single CSV to --output"
# Context: Output Location & Mode. Nothing goes to stdout in directory mode.
def test_directory_mode_writes_nothing_to_stdout(csv_file, run_tool):
    csv_file("a.csv", "id,country\n1,US\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.stdout == ""
    assert result.stderr == ""


# Phrase: "When any partitioning flag provided: --output must be directory path"
# Context: Output Location & Mode. Ambiguity T40: no rows still creates the directory.
def test_empty_input_creates_the_output_directory(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,country\n")
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "country", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "out").is_dir()
    assert tree(workdir / "out") == []
