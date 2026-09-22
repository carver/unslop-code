"""`errors` -- spec: New Subcommands / errors."""

import json


# ---------------------------------------------------------------------------
# "python sith.py errors <file>" / "Report syntax errors in the file."
# ---------------------------------------------------------------------------

def test_errors_accepts_a_single_file_argument(rhelpers, tmp_path):
    r = rhelpers.errors_raw(tmp_path, {"main.py": "x = 1\n"}, project=False)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert json.loads(r.stdout) == {"errors": []}


def test_errors_reports_a_syntax_error(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    assert len(found) >= 1


# ---------------------------------------------------------------------------
# "If the file has no syntax errors, return {"errors":[]} and exit 0."
# ---------------------------------------------------------------------------

def test_clean_file_reports_no_errors(rhelpers, tmp_path):
    assert rhelpers.syntax_errors(tmp_path, {
        "main.py": "def f(a, b):\n    return a + b\n\n\nclass C:\n    pass\n",
    }) == []


def test_empty_file_reports_no_errors(rhelpers, tmp_path):
    assert rhelpers.syntax_errors(tmp_path, {"main.py": ""}) == []


def test_clean_file_payload_has_the_errors_key(rhelpers, tmp_path):
    r = rhelpers.errors_raw(tmp_path, {"main.py": "x = 1\n"})
    assert json.loads(r.stdout) == {"errors": []}


# ---------------------------------------------------------------------------
# "`line` | int | 1-based start line."
# "`column` | int | 0-based start column."
# "`until_line` | int | 1-based end line."
# "`until_column` | int | 0-based end column."
# "`message` | string | Error description from the parser."
# ---------------------------------------------------------------------------

def test_error_entry_has_every_documented_field(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    entry = found[0]
    assert set(entry) == {"line", "column", "until_line", "until_column",
                          "message"}
    for key in ("line", "column", "until_line", "until_column"):
        assert isinstance(entry[key], int), key
    assert isinstance(entry["message"], str)


def test_start_line_is_one_based(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    assert found[0]["line"] == 3


def test_start_column_is_zero_based(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    assert found[0]["column"] == 4


def test_end_position_is_at_or_after_the_start(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    entry = found[0]
    assert (entry["until_line"], entry["until_column"]) >= (entry["line"],
                                                            entry["column"])


def test_message_is_non_empty(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    assert found[0]["message"]


def test_message_describes_invalid_syntax(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = 2\nz = = 3\n"})
    assert "syntax" in found[0]["message"].lower()


def test_unclosed_bracket_is_reported(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "x = 1\ny = (\nz = 3\n"})
    assert len(found) >= 1
    assert found[0]["line"] == 2
    assert found[0]["column"] == 4


def test_missing_colon_is_reported(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "def f()\n    pass\n"})
    assert len(found) >= 1
    assert found[0]["line"] == 1


def test_bad_indentation_is_reported(rhelpers, tmp_path):
    found = rhelpers.syntax_errors(tmp_path, {"main.py": "def f():\npass\n"})
    assert len(found) >= 1


# ---------------------------------------------------------------------------
# "Exit 0 regardless of whether syntax errors are found -- the errors array is
#  the output, not a tool failure."
# ---------------------------------------------------------------------------

def test_exit_zero_even_with_a_syntax_error(rhelpers, tmp_path):
    r = rhelpers.errors_raw(tmp_path, {"main.py": "def f(:\n"})
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert json.loads(r.stdout)["errors"]


def test_stdout_is_json_when_errors_exist(rhelpers, tmp_path):
    r = rhelpers.errors_raw(tmp_path, {"main.py": "def f(:\n"})
    payload = json.loads(r.stdout)
    assert list(payload) == ["errors"]


# ---------------------------------------------------------------------------
# "Exit 1 only for tool-level failures (e.g., file not found)."
# ---------------------------------------------------------------------------

def test_missing_file_exits_one(rhelpers, tmp_path):
    r = rhelpers.run_raw(["errors", str(tmp_path / "nope.py")])
    assert r.returncode == 1


def test_missing_file_emits_no_errors_payload(rhelpers, tmp_path):
    r = rhelpers.run_raw(["errors", str(tmp_path / "nope.py")])
    assert '"errors"' not in r.stdout


def test_directory_argument_exits_one(rhelpers, tmp_path):
    (tmp_path / "sub").mkdir()
    r = rhelpers.run_raw(["errors", str(tmp_path / "sub")])
    assert r.returncode == 1
