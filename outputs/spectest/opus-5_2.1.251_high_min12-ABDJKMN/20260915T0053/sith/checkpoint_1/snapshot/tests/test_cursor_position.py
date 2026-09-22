"""Spec section: Cursor Position."""
import json

from conftest import has, run_complete, write_source


# --- Phrase: "<line> is 1-based."
#     Context: line 1 is the first line of the file.
def test_line_is_one_based(tmp_path):
    code = "first_name = 1\nsecond_name = 2\n"
    p = write_source(tmp_path, code)
    # On line 1 only `first_name` is defined yet (col 13 is just after "= ").
    data = json.loads(run_complete(p, 1, 13).stdout)
    assert has(data, "first_name")
    assert not has(data, "second_name")


# --- Phrase: "<col> is 0-based (number of characters before the cursor on that line)."
#     Context: col 0 is before the first character; col 3 of "abcd" is after "abc".
def test_col_is_zero_based_character_count(tmp_path):
    p = write_source(tmp_path, "alphabet = 1\nalph\n")
    data = json.loads(run_complete(p, 2, 3).stdout)
    # 3 characters before the cursor => prefix "alp"
    assert data["completions"][0]["complete"] == "habet" or has(data, "alphabet")
    assert json.loads(run_complete(p, 2, 0).stdout)["completions"], "col 0 is valid"


# --- Phrase: "If the position is out of range (line exceeds file length ...), exit 1."
#     Context: file has 2 lines.
def test_line_beyond_end_of_file_exits_1(tmp_path):
    p = write_source(tmp_path, "a = 1\nb = 2\n")
    proc = run_complete(p, 9, 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# --- Phrase: "line exceeds file length"
#     Context: line 0 and negatives are not 1-based positions either.
def test_line_zero_exits_1(tmp_path):
    p = write_source(tmp_path, "a = 1\n")
    assert run_complete(p, 0, 0).returncode == 1


# --- Phrase: "or column exceeds line length"
#     Context: line "a = 1" has length 5, so col 6 is out of range.
def test_column_beyond_line_length_exits_1(tmp_path):
    p = write_source(tmp_path, "a = 1\nbb\n")
    assert run_complete(p, 2, 3).returncode == 1
    assert run_complete(p, 1, 6).returncode == 1


# --- Phrase: "or column exceeds line length"
#     Context: a cursor exactly at end-of-line does not exceed the length.
def test_column_at_end_of_line_is_valid(tmp_path):
    p = write_source(tmp_path, "a = 1\n")
    proc = run_complete(p, 1, 5)
    assert proc.returncode == 0


# --- Phrase: "column exceeds line length"
#     Context: negative column is out of range.
def test_negative_column_exits_1(tmp_path):
    p = write_source(tmp_path, "a = 1\n")
    assert run_complete(p, 1, -1).returncode == 1


# --- Phrase: "line exceeds file length" (T1)
#     Context: trailing newline yields a final empty line the cursor may sit on.
def test_position_on_empty_line_after_trailing_newline(tmp_path):
    p = write_source(tmp_path, "value = 1\n")
    proc = run_complete(p, 2, 0)
    assert proc.returncode == 0
    assert has(json.loads(proc.stdout), "value")


# --- Phrase: "line exceeds file length" (T2)
#     Context: an empty file still has position 1,0.
def test_empty_file_position_one_zero(tmp_path):
    p = write_source(tmp_path, "")
    proc = run_complete(p, 1, 0)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert has(data, "print") and has(data, "import")
