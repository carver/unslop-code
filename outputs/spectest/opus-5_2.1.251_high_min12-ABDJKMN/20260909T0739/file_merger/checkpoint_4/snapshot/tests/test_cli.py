"""CLI surface: the `Usage` block of the spec."""
import sys

from conftest import merge, run, write, write_schema


# --- Spec: "Write `merge_files.py` with the following interface." -------------
def test_tool_file_exists(tool):
    assert tool.is_file()


# --- Spec: usage synopsis is accepted; --help works --------------------------
def test_help_exits_zero():
    r = run("--help")
    assert r.ok, r
    assert "--output" in r.stdout
    assert "--key" in r.stdout


# --- Spec: "python merge_files.py --output <PATH|-> --key <col>[,<col>...]" ---
# --output is part of the required interface.
def test_output_flag_is_required(tmp_path):
    write(tmp_path, "a.csv", "id\n1\n")
    r = run("--key", "id", tmp_path / "a.csv")
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "--key <col>[,<col>...]" is not bracketed => required --------------
def test_key_flag_is_required(tmp_path):
    write(tmp_path, "a.csv", "id\n1\n")
    r = run("--output", "-", tmp_path / "a.csv")
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "<INPUT1.csv> [<INPUT2.csv> ...]" => at least one input ------------
def test_at_least_one_input_required():
    r = run("--output", "-", "--key", "id")
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "<INPUT1.csv> [<INPUT2.csv> ...]" => many inputs accepted ----------
def test_many_inputs_accepted(tmp_path):
    files = {f"f{i}.csv": f"id\n{i}\n" for i in range(5)}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id"], ["0"], ["1"], ["2"], ["3"], ["4"]]


# --- Spec: "[--infer {strict,loose}]" ----------------------------------------
def test_infer_choices(tmp_path):
    files = {"a.csv": "id\n1\n"}
    for mode in ("strict", "loose"):
        assert merge(tmp_path, files, "--key", "id", "--infer", mode).ok
    bad = merge(tmp_path, files, "--key", "id", "--infer", "sloppy")
    assert not bad.ok


# --- Spec: "[--on-type-error {coerce-null,fail,keep-string}]" ----------------
def test_on_type_error_choices(tmp_path):
    files = {"a.csv": "id\n1\n"}
    for mode in ("coerce-null", "fail", "keep-string"):
        assert merge(tmp_path, files, "--key", "id", "--on-type-error", mode).ok
    bad = merge(tmp_path, files, "--key", "id", "--on-type-error", "explode")
    assert not bad.ok


# --- Spec: "[--memory-limit-mb <INT>]" ---------------------------------------
def test_memory_limit_must_be_int(tmp_path):
    files = {"a.csv": "id\n1\n"}
    assert merge(tmp_path, files, "--key", "id", "--memory-limit-mb", "64").ok
    assert not merge(tmp_path, files, "--key", "id", "--memory-limit-mb", "lots").ok


# --- Spec: "[--desc]" is a flag, not a value ---------------------------------
def test_desc_is_a_flag(tmp_path):
    files = {"a.csv": "id\n1\n2\n"}
    r = merge(tmp_path, files, "--key", "id", "--desc")
    assert r.ok, r
    assert r.rows() == [["id"], ["2"], ["1"]]


# --- Spec: "--key <col>[,<col>...]" composite keys are comma separated -------
def test_key_accepts_comma_separated_columns(tmp_path):
    files = {"a.csv": "a,b\n1,2\n"}
    r = merge(tmp_path, files, "--key", "a,b")
    assert r.ok, r


# --- Spec ambiguity T22: repeating --key appends columns ---------------------
def test_key_flag_may_repeat(tmp_path):
    files = {"a.csv": "a,b\n10,2\n10,7\n"}
    r = merge(tmp_path, files, "--key", "a", "--key", "b")
    assert r.ok, r
    assert r.rows() == [["a", "b"], ["10", "2"], ["10", "7"]]


# --- Spec: inputs are file paths; a missing one is an error ------------------
def test_missing_input_file_is_an_error(tmp_path):
    r = run("--output", "-", "--key", "id", tmp_path / "nope.csv")
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "[--temp-dir <PATH>]" is accepted --------------------------------
def test_temp_dir_flag_accepted(tmp_path):
    tmp = tmp_path / "scratch"
    tmp.mkdir()
    files = {"a.csv": "id\n2\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--temp-dir", str(tmp))
    assert r.ok, r
    assert r.rows() == [["id"], ["2"], ["7"]]


# --- Spec: "[--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>]" accepted -----
def test_csv_char_flags_accepted(tmp_path):
    files = {"a.csv": "id\n1\n"}
    assert merge(tmp_path, files, "--key", "id", "--csv-quotechar", '"').ok
    assert merge(tmp_path, files, "--key", "id", "--csv-escapechar", "\\").ok


# --- Spec: "[--csv-null-literal <STRING>]" accepted --------------------------
def test_null_literal_flag_accepted(tmp_path):
    files = {"a.csv": "id\n1\n"}
    assert merge(tmp_path, files, "--key", "id", "--csv-null-literal", "NULL").ok
