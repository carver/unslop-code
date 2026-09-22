"""Spec section: Error Handling (and syntax-error tolerance)."""
import json

from conftest import CURSOR, complete_at, has, run_complete, write_source

C = CURSOR


# --- Phrase: "File does not exist or is not a regular file: exit 1, message to STDERR."
#     Context: missing path.
def test_missing_file(tmp_path):
    proc = run_complete(tmp_path / "does_not_exist.py", 1, 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# --- Phrase: "File does not exist or is not a regular file"
#     Context: a directory is not a regular file.
def test_directory_is_not_regular_file(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    proc = run_complete(d, 1, 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# --- Phrase: "File is not valid UTF-8: exit 1."
#     Context: invalid byte sequence in the source file.
def test_invalid_utf8(tmp_path):
    p = tmp_path / "bad.py"
    p.write_bytes(b"x = 1\ny = '\xff\xfe'\n")
    proc = run_complete(p, 1, 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# --- Phrase: "Line or column out of range: exit 1."
#     Context: both dimensions.
def test_out_of_range_exit_1(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    assert run_complete(p, 50, 0).returncode == 1
    assert run_complete(p, 1, 50).returncode == 1


# --- Phrase: "Python syntax errors in the source file: do not exit with an error."
#     Context: a broken line in the middle of the file.
def test_syntax_error_exits_zero(tmp_path):
    code = "value = 1\ndef broken(:\n    pass\n" + C + "\n"
    src, line, col = code.replace(C, ""), 4, 0
    p = write_source(tmp_path, src)
    proc = run_complete(p, line, col)
    assert proc.returncode == 0
    json.loads(proc.stdout)


# --- Phrase: "Parse as much as possible and provide completions based on what was successfully
#              parsed."
#     Context: definitions before the broken line survive.
def test_names_before_syntax_error_survive(tmp_path):
    code = (
        "good_before = 1\n"
        "def broken(:\n"
        "    pass\n"
        "goo" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "good_before")


# --- Phrase: "Parse as much as possible" (T17)
#     Context: definitions after the broken line survive too.
def test_names_after_syntax_error_survive(tmp_path):
    code = (
        "x = = = 3\n"
        "good_after = 1\n"
        "goo" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "good_after")


# --- Phrase: "Syntax errors are common during editing — the tool must be tolerant."
#     Context: the classic half-typed attribute access line.
def test_incomplete_attribute_line(tmp_path):
    code = (
        "import os\n"
        "def f():\n"
        "    os." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "getcwd")


# --- Phrase: "Syntax errors are common during editing"
#     Context: a dangling open bracket before the cursor.
def test_unclosed_bracket(tmp_path):
    code = (
        "widget = 1\n"
        "result = [\n"
        "wi" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "widget")


# --- Phrase: "Syntax errors are common during editing"
#     Context: a function whose body is not yet written.
def test_empty_function_body(tmp_path):
    code = (
        "def outer():\n"
        "\n"
        "widget = 1\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "widget")
    assert has(data, "outer")


# --- Phrase: "the tool must be tolerant"
#     Context: a badly indented line inside a function still lets locals through.
def test_bad_indentation(tmp_path):
    code = (
        "def f():\n"
        "    alpha = 1\n"
        "  beta_broken = 2\n"
        "    alp" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "alpha")


# --- Phrase: "Python syntax errors ... do not exit with an error"
#     Context: a file that is nothing but garbage still succeeds with keywords/builtins.
def test_total_garbage_file(tmp_path):
    code = "!!! ??? ***\n$$$\npri" + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "print")
