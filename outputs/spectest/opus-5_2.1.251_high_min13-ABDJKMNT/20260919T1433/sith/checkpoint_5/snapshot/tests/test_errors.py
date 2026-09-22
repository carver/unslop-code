"""Spec: New Subcommands / `errors`."""

from conftest import run_command


# Spec: "python sith.py errors <file>" / "Report syntax errors in the file."
def test_syntax_error_is_reported(errors):
    result = errors("x = = 1\n")
    assert result.code == 0
    assert len(result.syntax_errors) == 1


# Spec: fields "line" (1-based start line), "column" (0-based start column),
# "until_line", "until_column", "message".
def test_error_carries_the_specified_fields(errors):
    [error] = errors("x = = 1\n").syntax_errors
    assert list(error) == ["line", "column", "until_line", "until_column", "message"]
    assert (error["line"], error["column"]) == (1, 4)
    assert (error["until_line"], error["until_column"]) == (1, 5)
    assert isinstance(error["message"], str) and error["message"]


# Spec: "`line` | int | 1-based start line."
def test_line_is_one_based(errors):
    [error] = errors("x = 1\ny = = 2\n").syntax_errors
    assert error["line"] == 2


# Spec: "`message` | string | Error description from the parser."
def test_message_comes_from_the_parser(errors):
    [error] = errors("def f():\npass\n").syntax_errors
    assert "expected an indented block" in error["message"]


# Spec: "If the file has no syntax errors, return {"errors":[]} and exit 0."
def test_clean_file_reports_no_errors(errors):
    result = errors("x = 1\n\n\ndef helper():\n    return x\n")
    assert result.code == 0
    assert result.stdout == '{"errors":[]}\n'


# Spec: "Exit 0 regardless of whether syntax errors are found."
def test_broken_file_still_exits_zero(errors):
    assert errors("def broken(:\n    pass\n").code == 0


# Spec: "Exit 1 only for tool-level failures (e.g., file not found)."
def test_missing_file_exits_one(tmp_path):
    result = run_command("errors", tmp_path / "missing.py")
    assert result.code == 1
    assert result.stderr.strip()
    assert result.stdout == ""
