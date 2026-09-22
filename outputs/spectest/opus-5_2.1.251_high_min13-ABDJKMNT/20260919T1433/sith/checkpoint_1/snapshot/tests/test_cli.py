"""Spec: Deliverables, Cursor Position, and Error Handling."""

import json

from conftest import run


# Spec: "python sith.py complete <file> <line> <col> [--fuzzy]"
def test_complete_subcommand_is_accepted(complete):
    result = complete("x = 1\nx$\n")
    assert result.code == 0


# Spec: "Output is JSON to STDOUT - a single JSON object with a `completions` array."
def test_output_is_single_object_with_completions_array(complete):
    result = complete("value = 1\nval$\n")
    payload = json.loads(result.stdout)
    assert list(payload) == ["completions"]
    assert isinstance(payload["completions"], list)


# Spec: "Compact format: no extra whitespace."
def test_output_is_compact(complete):
    result = complete("value = 1\nval$\n")
    assert result.stdout.rstrip("\n") == json.dumps(
        json.loads(result.stdout), separators=(",", ":")
    )
    assert ", " not in result.stdout
    assert ": " not in result.stdout


# Spec: "Newline-terminated."
def test_output_is_newline_terminated(complete):
    result = complete("value = 1\nval$\n")
    assert result.stdout.endswith("\n")
    assert not result.stdout[:-1].endswith("\n")


# Spec: "On success, exit 0 (even with zero completions)."
def test_zero_completions_still_exits_zero(complete):
    result = complete("x = 1\nqqqqzzzz$\n")
    assert result.code == 0
    assert result.items == []


# Spec: "On error, print a message to STDERR and exit 1."
def test_error_writes_to_stderr_and_exits_one(tmp_path):
    result = run(tmp_path / "missing.py", 1, 0)
    assert result.code == 1
    assert result.stderr.strip()
    assert result.stdout == ""


# Spec: "<line> is 1-based."
def test_line_is_one_based(write):
    path = write("alpha = 1\nbeta = 2\nal\n")
    assert "alpha" in run(path, 3, 2).names


# Spec: "<col> is 0-based (number of characters before the cursor on that line)."
def test_col_is_zero_based(write):
    path = write("alpha = 1\nal\n")
    at_start = run(path, 2, 0)
    at_two = run(path, 2, 2)
    assert "alpha" in at_start.names
    assert at_two.by_name("alpha")["complete"] == "pha"


# Spec: "If the position is out of range (line exceeds file length ...), exit 1."
def test_line_out_of_range_exits_one(write):
    path = write("x = 1\n")
    result = run(path, 99, 0)
    assert result.code == 1
    assert result.stderr.strip()


# Spec: "... or column exceeds line length), exit 1."
def test_column_out_of_range_exits_one(write):
    path = write("x = 1\n")
    result = run(path, 1, 99)
    assert result.code == 1
    assert result.stderr.strip()


# Spec: "<col> is ... the number of characters before the cursor" - end of line is valid.
def test_column_at_end_of_line_is_valid(write):
    path = write("x = 1\n")
    assert run(path, 1, 5).code == 0


# Spec: "File does not exist or is not a regular file: exit 1, message to STDERR."
def test_missing_file_exits_one(tmp_path):
    result = run(tmp_path / "nope.py", 1, 0)
    assert result.code == 1
    assert result.stderr.strip()


def test_directory_is_not_a_regular_file(tmp_path):
    result = run(tmp_path, 1, 0)
    assert result.code == 1
    assert result.stderr.strip()


# Spec: "File is not valid UTF-8: exit 1."
def test_invalid_utf8_exits_one(write):
    path = write(b"x = '\xff\xfe'\n")
    result = run(path, 1, 0)
    assert result.code == 1
    assert result.stderr.strip()
