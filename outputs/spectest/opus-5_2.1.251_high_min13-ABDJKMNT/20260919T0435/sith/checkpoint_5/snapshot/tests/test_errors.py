"""The `errors` command: syntax errors reported as data."""

from conftest import run_cli


# "python sith.py errors <file>"
def test_errors_accepts_a_file(errors):
    assert errors("x = 1\n").returncode == 0


# "If the file has no syntax errors, return `{\"errors\":[]}` and exit 0."
def test_a_clean_file_reports_nothing(errors):
    result = errors("def f(a):\n    return a\n")
    assert result.stdout == '{"errors":[]}\n'
    assert result.returncode == 0


def test_an_empty_file_reports_nothing(errors):
    assert errors("").errors == []


# "Report syntax errors in the file."
def test_a_syntax_error_is_reported(errors):
    assert len(errors("def f(:\n    pass\n").errors) == 1


def test_an_unclosed_bracket_is_reported(errors):
    assert errors("x = (1 + 2\n").errors != []


def test_a_bad_indent_is_reported(errors):
    assert errors("def f():\n    x = 1\n      y = 2\n").errors != []


# "| `line` | int | 1-based start line. |"
def test_the_start_line_is_one_based(errors):
    reported = errors("x = 1\ny = *\n").errors[0]
    assert reported["line"] == 2


# "| `column` | int | 0-based start column. |"
def test_the_start_column_is_zero_based(errors):
    reported = errors("x = 1 1\n").errors[0]
    assert reported["column"] >= 0
    assert reported["column"] < len("x = 1 1")


# "| `until_line` | int | 1-based end line. | `until_column` | int | 0-based end column. |"
def test_the_end_position_is_at_or_after_the_start(errors):
    reported = errors("x = 1 1\n").errors[0]
    assert (reported["until_line"], reported["until_column"]) >= (
        reported["line"], reported["column"]
    )


# "| `message` | string | Error description from the parser. |"
def test_the_message_comes_from_the_parser(errors):
    reported = errors("x = (1 + 2\n").errors[0]
    assert isinstance(reported["message"], str)
    assert reported["message"] != ""


def test_error_object_field_set(errors):
    reported = errors("def f(:\n    pass\n").errors[0]
    assert set(reported) == {"line", "column", "until_line", "until_column", "message"}


# "Exit 0 regardless of whether syntax errors are found"
def test_a_broken_file_still_exits_zero(errors):
    assert errors("def f(:\n    pass\n").returncode == 0


# "the errors array is the output, not a tool failure"
def test_the_payload_is_one_array(errors):
    payload = errors("def f(:\n    pass\n").payload
    assert list(payload) == ["errors"]


# "Exit 1 only for tool-level failures (e.g., file not found)."
def test_a_missing_file_fails(workdir):
    result = run_cli("errors", str(workdir / "missing.py"))
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() != ""


def test_a_directory_is_a_tool_level_failure(workdir):
    assert run_cli("errors", str(workdir)).returncode == 1
