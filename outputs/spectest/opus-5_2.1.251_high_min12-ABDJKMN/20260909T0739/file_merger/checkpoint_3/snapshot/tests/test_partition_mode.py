"""The `Output Location & Mode` section of the partitioned-output spec."""
from pathlib import Path

from conftest import read_text, run, tree, write


# --- Spec: "When no partitioning flags provided: write single CSV to
#     `--output` (file path or `-` for stdout)" ------------------------------
def test_no_partition_flags_still_writes_single_file(tmp_path):
    a = write(tmp_path, "a.csv", "id\n2\n1\n")
    out = tmp_path / "merged.csv"
    r = run("--output", str(out), "--key", "id", str(a))
    assert r.ok, r
    assert out.is_file()
    assert read_text(out) == "id\n1\n2\n"


# --- Spec: "(file path or `-` for stdout)" with no partitioning flags -------
def test_no_partition_flags_still_writes_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id\n2\n1\n")
    r = run("--output", "-", "--key", "id", str(a))
    assert r.ok, r
    assert r.stdout == "id\n1\n2\n"


# --- Spec: "When any partitioning flag provided: `--output` must be directory
#     path (not `-`)" -- --partition-by ------------------------------------
def test_partition_by_rejects_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id,c\n1,us\n")
    r = run("--output", "-", "--key", "id", "--partition-by", "c", str(a))
    assert r.returncode == 2, r
    assert r.stderr.strip()
    assert r.stdout == ""


# --- Spec: "When any partitioning flag provided" -- --max-rows-per-file -----
def test_max_rows_rejects_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = run("--output", "-", "--key", "id", "--max-rows-per-file", "10", str(a))
    assert r.returncode == 2, r


# --- Spec: "When any partitioning flag provided" -- --max-bytes-per-file ----
def test_max_bytes_rejects_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = run("--output", "-", "--key", "id", "--max-bytes-per-file", "100", str(a))
    assert r.returncode == 2, r


# --- Spec: "`--output` must be directory path": an existing plain file at
#     that path cannot become the output directory --------------------------
def test_output_existing_file_rejected(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    out = write(tmp_path, "out", "not a directory\n")
    r = run("--output", str(out), "--key", "id", "--max-rows-per-file", "1", str(a))
    assert r.returncode == 2, r
    assert read_text(out) == "not a directory\n"


# --- Spec: "Create directory if doesn't exist" ------------------------------
def test_output_directory_created(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--max-rows-per-file", "1", str(a))
    assert r.ok, r
    assert out.is_dir()
    assert tree(out) == ["part-00000.csv"]


# --- Spec: "Create directory if doesn't exist" -- a trailing slash and a
#     missing parent are both acceptable spellings of the target ------------
def test_output_directory_created_nested(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    out = tmp_path / "deep" / "out"
    r = run("--output", str(out) + "/", "--key", "id", "--max-rows-per-file", "1",
            str(a))
    assert r.ok, r
    assert tree(out) == ["part-00000.csv"]


# --- Spec: "Create directory if doesn't exist" -- an already existing (empty)
#     directory is used as-is ----------------------------------------------
def test_output_directory_may_already_exist(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    out = tmp_path / "out"
    out.mkdir()
    r = run("--output", str(out), "--key", "id", "--max-rows-per-file", "1", str(a))
    assert r.ok, r
    assert tree(out) == ["part-00000.csv"]


# --- Spec: "Perform atomic write by creating sibling temp directory and
#     renaming on success": no temp artifacts survive a successful run ------
def test_no_temp_artifacts_left_on_success(tmp_path):
    a = write(tmp_path, "a.csv", "id,c\n1,us\n2,de\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "c", str(a))
    assert r.ok, r
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["a.csv", "out"], siblings


# --- Spec: "On failure, remove temp directory and partial files" ------------
def test_failure_leaves_no_output_and_no_temp(tmp_path):
    # A cast failure under --on-type-error fail aborts the run.
    schema = write(tmp_path, "s.json",
                   '{"columns":[{"name":"id","type":"int"},'
                   '{"name":"n","type":"int"}]}')
    a = write(tmp_path, "a.csv", "id,n\n1,7\n2,oops\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "id",
            "--on-type-error", "fail", "--schema", str(schema), str(a))
    assert r.returncode != 0, r
    leftovers = sorted(p.name for p in tmp_path.iterdir())
    assert leftovers == ["a.csv", "s.json"], leftovers


# --- Spec: "On failure, remove temp directory and partial files": a
#     pre-existing output directory is not damaged by a failed run ----------
def test_failure_keeps_previous_directory_intact(tmp_path):
    schema = write(tmp_path, "s.json",
                   '{"columns":[{"name":"id","type":"int"},'
                   '{"name":"n","type":"int"}]}')
    a = write(tmp_path, "a.csv", "id,n\n1,7\n2,oops\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "keepme.csv").write_text("old\n", encoding="utf-8")
    r = run("--output", str(out), "--key", "id", "--max-rows-per-file", "1",
            "--on-type-error", "fail", "--schema", str(schema), str(a))
    assert r.returncode != 0, r
    assert (out / "keepme.csv").read_text(encoding="utf-8") == "old\n"
    assert tree(out) == ["keepme.csv"]


# --- Spec: partitioned runs print nothing on stdout -------------------------
def test_partitioned_run_is_silent_on_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id,c\n1,us\n")
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "c", str(a))
    assert r.ok, r
    assert r.stdout == ""
