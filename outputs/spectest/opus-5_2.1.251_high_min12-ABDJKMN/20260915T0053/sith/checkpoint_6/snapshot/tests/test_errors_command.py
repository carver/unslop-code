"""Spec section: the `errors` subcommand."""
import json

from conftest import errors_raw, errors_at, run_raw, write_source

BROKEN = "x = 1\ny = = 2\n"


# --- Phrase: "python sith.py errors <file>" — "Report syntax errors in the
#     file."
def test_errors_command_exists(tmp_path):
    proc = errors_raw(tmp_path, BROKEN)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"errors"}


# --- Phrase: "If the file has no syntax errors, return `{"errors":[]}` and
#     exit 0."
def test_clean_file_reports_no_errors(tmp_path):
    proc = errors_raw(tmp_path, "x = 1\n\n\ndef f():\n    return x\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == '{"errors":[]}'


# --- Phrase: "Exit 0 regardless of whether syntax errors are found — the
#     errors array is the output, not a tool failure."
def test_syntax_error_still_exits_0(tmp_path):
    proc = errors_raw(tmp_path, BROKEN)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["errors"] != []


# --- Phrase: the entry's five fields.
def test_error_entry_fields(tmp_path):
    entry = errors_at(tmp_path, BROKEN)[0]
    assert set(entry) == {"line", "column", "until_line", "until_column",
                          "message"}


# --- Phrase: "line | int | 1-based start line."
def test_line_is_1_based(tmp_path):
    assert errors_at(tmp_path, BROKEN)[0]["line"] == 2


# --- Phrase: "column | int | 0-based start column."
def test_column_is_0_based(tmp_path):
    assert errors_at(tmp_path, BROKEN)[0]["column"] == 4


# --- Phrase: "until_line | int | 1-based end line." and
#     "until_column | int | 0-based end column."
def test_until_positions(tmp_path):
    entry = errors_at(tmp_path, BROKEN)[0]
    assert entry["until_line"] == 2
    assert entry["until_column"] == 5


# --- Phrase: "message | string | Error description from the parser."
def test_message_comes_from_the_parser(tmp_path):
    entry = errors_at(tmp_path, BROKEN)[0]
    assert entry["message"] == "invalid syntax"


def test_missing_colon_message(tmp_path):
    entry = errors_at(tmp_path, "if True\n    pass\n")[0]
    assert "expected ':'" in entry["message"]
    assert entry["line"] == 1
    assert entry["column"] == 7


# --- Phrase: an unclosed bracket still reports a usable position.
def test_unclosed_bracket(tmp_path):
    entry = errors_at(tmp_path, "x = (1\n")[0]
    assert entry["line"] == 1
    assert entry["column"] == 4
    assert entry["until_column"] >= entry["column"]


# --- Phrase: "Exit 1 only for tool-level failures (e.g., file not found)."
def test_missing_file_exits_1(tmp_path):
    proc = run_raw("errors", str(tmp_path / "nope.py"), cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_directory_exits_1(tmp_path):
    proc = run_raw("errors", str(tmp_path), cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: an empty file has no syntax errors.
def test_empty_file(tmp_path):
    assert errors_at(tmp_path, "") == []


# --- Phrase: the tolerant repair used by the other commands does not hide the
#     error here.
def test_errors_reported_even_though_other_commands_recover(tmp_path):
    path = write_source(tmp_path, BROKEN, "broken.py")
    assert errors_at(tmp_path, BROKEN) != []
    goto = run_raw("goto", str(path), 1, 0, cwd=str(tmp_path))
    assert goto.returncode == 0, goto.stderr
