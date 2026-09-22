"""`Usage` additions introduced by the multi-format checkpoint."""
from conftest import merge_paths, run, write, write_jsonl


# --- Spec usage line: the new flags are accepted ---------------------------
def test_all_new_flags_accepted_together(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n7,x\n")
    r = merge_paths(
        [a], "--key", "id",
        "--infer", "loose",
        "--schema-strategy", "union",
        "--on-type-error", "coerce-null",
        "--memory-limit-mb", "64",
        "--temp-dir", str(tmp_path),
        "--csv-quotechar", '"',
        "--csv-null-literal", "",
        "--input-format", "csv",
        "--compression", "none",
        "--parquet-row-group-bytes", "65536",
    )
    assert r.ok, r
    assert r.rows() == [["id", "v"], ["7", "x"]]


# --- Spec usage: "--input-format {auto,csv,tsv,jsonl,parquet}" ------------
def test_input_format_choices_listed_in_help():
    r = run("--help")
    assert r.ok, r
    for token in ("--input-format", "--compression", "--schema-strategy",
                  "--parquet-row-group-bytes"):
        assert token in r.stdout


def test_bad_input_format_value_rejected(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = merge_paths([a], "--key", "id", "--input-format", "orc")
    assert r.returncode == 2, r


# --- Spec usage: "--parquet-row-group-bytes <INT>" ------------------------
def test_row_group_bytes_must_be_an_integer(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = merge_paths([a], "--key", "id", "--parquet-row-group-bytes", "big")
    assert r.returncode == 2, r


def test_row_group_bytes_must_be_positive(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = merge_paths([a], "--key", "id", "--parquet-row-group-bytes", "0")
    assert r.returncode == 2, r


# --- Spec usage: "<INPUT1> [<INPUT2> ...]" - several inputs of any type ----
def test_many_inputs_accepted(tmp_path):
    paths = [write_jsonl(tmp_path, f"f{i}.jsonl", [{"id": i}]) for i in range(6)]
    r = merge_paths(paths, "--key", "id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == [str(i) for i in range(6)]


# --- Spec usage: "--output <PATH|->" is still required --------------------
def test_output_is_required(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = run("--key", "id", str(a), cwd=tmp_path)
    assert r.returncode == 2, r


# --- Spec: a missing input file is a bad invocation ------------------------
def test_missing_input_file_is_error_2(tmp_path):
    r = run("--output", "-", "--key", "id", str(tmp_path / "nope.csv"),
            cwd=tmp_path)
    assert r.returncode == 2, r
