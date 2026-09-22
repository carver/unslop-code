"""Cursor addressing and range validation."""
from conftest import run_cli


# Spec: "<line> is 1-based." - line 1 addresses the first physical line.
def test_line_is_one_based(complete):
    result = complete("beta = 2\nalpha = 1\n", line=1, col=0)
    assert "alpha" not in result.names


# Spec: "<line> is 1-based." - line 2 sees the line-1 assignment.
def test_line_two_sees_line_one_definition(complete):
    result = complete("alpha = 1\nbeta = 2\n", line=2, col=0)
    assert "alpha" in result.names


# Spec: "<col> is 0-based (number of characters before the cursor on that line)."
def test_col_counts_characters_before_cursor(complete):
    # "al" precedes the cursor at col 2, so the prefix is "al".
    result = complete("alpha = 1\nalx\n", line=2, col=2)
    assert "alpha" in result.names
    assert result.by_name("alpha")["complete"] == "pha"


# Spec: "If the position is out of range (line exceeds file length ...), exit 1."
def test_line_beyond_end_of_file_exits_one(complete):
    result = complete("x = 1\n", line=50, col=0, expect_ok=False)
    assert result.returncode == 1
    assert result.stderr.strip() != ""


# Spec: "(... or column exceeds line length), exit 1."
def test_column_beyond_line_length_exits_one(complete):
    result = complete("x = 1\n", line=1, col=99, expect_ok=False)
    assert result.returncode == 1


# Spec: column exactly at end-of-line is in range (0-based count of preceding chars).
def test_column_at_end_of_line_is_in_range(complete):
    result = complete("x = 1\n", line=1, col=5)
    assert result.returncode == 0


# Spec: "line exceeds file length" - line 0 and negative columns are out of range.
def test_nonpositive_line_exits_one(complete):
    assert complete("x = 1\n", line=0, col=0, expect_ok=False).returncode == 1


def test_negative_column_exits_one(complete):
    assert complete("x = 1\n", line=1, col=-1, expect_ok=False).returncode == 1


# Spec: line/col must be integers for the CLI to address a position.
def test_non_integer_position_exits_one(workdir):
    path = workdir / "s.py"
    path.write_text("x = 1\n", encoding="utf-8")
    assert run_cli("complete", str(path), "abc", 0).returncode == 1
