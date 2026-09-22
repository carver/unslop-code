"""Checkpoint 3: choosing between single-file output and a partitioned directory."""


def test_no_partitioning_flags_still_write_a_single_csv_file(run_cli, csv_file, tmp_path):
    # Spec: "When no partitioning flags provided: write single CSV to --output (file path ...)"
    a = csv_file("a.csv", "id,note\n2,b\n1,a\n")
    out = tmp_path / "merged.csv"
    result = run_cli("--output", out, "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == "id,note\n1,a\n2,b\n"


def test_no_partitioning_flags_still_write_to_stdout(run_cli, csv_file):
    # Spec: "When no partitioning flags provided: write single CSV to --output (... or `-` for stdout)"
    a = csv_file("a.csv", "id\n2\n1\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "id\n1\n2\n"


def test_partition_by_makes_output_a_directory(run_cli, csv_file, tmp_path):
    # Spec: "When any partitioning flag provided: --output must be directory path"
    a = csv_file("a.csv", "id,g\n1,x\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert result.returncode == 0, result.stderr
    assert out.is_dir()


def test_max_rows_makes_output_a_directory(run_cli, csv_file, tmp_path):
    # Spec: "When any partitioning flag provided: --output must be directory path"
    a = csv_file("a.csv", "id\n1\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--max-rows-per-file", "10", a)
    assert result.returncode == 0, result.stderr
    assert (out / "part-00000.csv").is_file()


def test_max_bytes_makes_output_a_directory(run_cli, csv_file, tmp_path):
    # Spec: "When any partitioning flag provided: --output must be directory path"
    a = csv_file("a.csv", "id\n1\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "1000", a)
    assert result.returncode == 0, result.stderr
    assert (out / "part-00000.csv").is_file()


def test_stdout_output_is_rejected_when_partitioning(run_cli, csv_file):
    # Spec: "--output must be directory path (not `-`)" (exit code: AMBIGUITIES T38)
    a = csv_file("a.csv", "id,g\n1,x\n")
    result = run_cli("--output", "-", "--key", "id", "--partition-by", "g", a)
    assert result.returncode == 1
    assert result.stderr.strip()
    assert result.stdout == ""


def test_stdout_output_is_rejected_when_sharding(run_cli, csv_file):
    # Spec: "--output must be directory path (not `-`)" (exit code: AMBIGUITIES T38)
    a = csv_file("a.csv", "id\n1\n")
    result = run_cli("--output", "-", "--key", "id", "--max-rows-per-file", "5", a)
    assert result.returncode == 1
    assert result.stderr.strip()


def test_existing_file_at_output_path_is_rejected(run_cli, csv_file, tmp_path):
    # Spec: "--output must be directory path" (AMBIGUITIES T38)
    a = csv_file("a.csv", "id\n1\n")
    out = tmp_path / "out"
    out.write_text("not a directory", encoding="utf-8")
    result = run_cli("--output", out, "--key", "id", "--max-rows-per-file", "5", a)
    assert result.returncode == 1
    assert out.read_text(encoding="utf-8") == "not a directory"


def test_output_directory_is_created_when_missing(run_cli, csv_file, tmp_path):
    # Spec: "Create directory if doesn't exist"
    a = csv_file("a.csv", "id,g\n1,x\n")
    out = tmp_path / "nested" / "out"
    result = run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert result.returncode == 0, result.stderr
    assert (out / "g=x" / "part-00000.csv").is_file()


def test_existing_output_directory_is_replaced(run_cli, csv_file, tmp_path, tree):
    # Spec: "Perform atomic write by creating sibling temp directory and renaming on
    # success" — the renamed directory holds this run's output only (AMBIGUITIES T34)
    a = csv_file("a.csv", "id,g\n1,x\n")
    out = tmp_path / "out"
    (out / "stale").mkdir(parents=True)
    (out / "stale" / "old.csv").write_text("stale", encoding="utf-8")
    result = run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert result.returncode == 0, result.stderr
    assert tree(out) == ["g=x/part-00000.csv"]


def test_successful_run_leaves_no_temp_directory_behind(run_cli, csv_file, tmp_path):
    # Spec: "creating sibling temp directory and renaming on success"
    a = csv_file("a.csv", "id,g\n1,x\n2,y\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert result.returncode == 0, result.stderr
    assert [path.name for path in out.parent.iterdir() if path.is_dir()] == ["out"]


def test_failed_run_removes_the_temp_directory_and_partial_files(run_cli, csv_file, tmp_path):
    # Spec: "On failure, remove temp directory and partial files"
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"columns": [{"name": "id", "type": "int"}, {"name": "g", "type": "string"}]}',
        encoding="utf-8",
    )
    a = csv_file("a.csv", "id,g\n1,x\nnope,y\n")
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "id", "--partition-by", "g",
        "--schema", schema, "--on-type-error", "fail", a,
    )
    assert result.returncode == 4
    assert not out.exists()
    assert [path.name for path in out.parent.iterdir() if path.is_dir()] == []


def test_partition_column_missing_from_schema_is_an_error(run_cli, csv_file, tmp_path):
    # Spec: partition columns name columns of the resolved schema (AMBIGUITIES T40)
    a = csv_file("a.csv", "id,g\n1,x\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--partition-by", "nope", a)
    assert result.returncode == 3
    assert "nope" in result.stderr


def test_non_positive_limits_are_rejected(run_cli, csv_file, tmp_path):
    # Spec: "--max-rows-per-file <INT>" / "--max-bytes-per-file <INT>" (AMBIGUITIES T44)
    a = csv_file("a.csv", "id\n1\n")
    out = tmp_path / "out"
    assert run_cli("--output", out, "--key", "id", "--max-rows-per-file", "0", a).returncode != 0
    assert run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "-1", a).returncode != 0
