"""Command-line interface surface of merge_files.py."""

from conftest import rows_of


# Spec: "python merge_files.py --output <PATH|-> --key <col>[,<col>...] ... <INPUT1.csv> [<INPUT2.csv> ...]"
# Context: --output and --key are non-optional parts of the usage line.
def test_output_flag_is_required(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--key", "id", "a.csv", expect_ok=False)
    assert proc.returncode != 0


def test_key_flag_is_required(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "a.csv", expect_ok=False)
    assert proc.returncode != 0


# Spec: "<INPUT1.csv> [<INPUT2.csv> ...]" - at least one input is required.
def test_at_least_one_input_is_required(run):
    proc = run("--output", "-", "--key", "id", expect_ok=False)
    assert proc.returncode != 0


# Spec: "[--infer {strict,loose}]" - only the two listed modes are accepted.
def test_infer_mode_is_restricted_to_listed_choices(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "--key", "id", "--infer", "sloppy", "a.csv", expect_ok=False)
    assert proc.returncode != 0


# Spec: "[--on-type-error {coerce-null,fail,keep-string}]"
def test_on_type_error_is_restricted_to_listed_choices(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "--key", "id", "--on-type-error", "explode", "a.csv", expect_ok=False)
    assert proc.returncode != 0


# Spec: "--key <col>[,<col>...]" - a composite key is given as one comma separated value.
def test_key_accepts_comma_separated_columns(make_csv, run):
    make_csv("a.csv", "id,ts\n2,2024-01-01T00:00:00Z\n1,2024-01-01T00:00:00Z\n")
    proc = run("--output", "-", "--key", "ts,id", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["1", "2024-01-01T00:00:00Z"], ["2", "2024-01-01T00:00:00Z"]]


# Spec: "[--memory-limit-mb <INT>]" - the limit is an integer.
def test_memory_limit_must_be_an_integer(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "--key", "id", "--memory-limit-mb", "lots", "a.csv", expect_ok=False)
    assert proc.returncode != 0


# Spec: "All inputs are UTF-8" - a non existing input path is a tool error, not a traceback.
def test_missing_input_file_exits_non_zero_with_stderr(run):
    proc = run("--output", "-", "--key", "id", "nope.csv", expect_ok=False)
    assert proc.returncode != 0
    assert proc.stderr.strip()
