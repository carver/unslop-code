"""Star imports, local project modules, and error handling."""
from conftest import run_cli


# Spec: "`import os` makes `os` visible as a module."
def test_import_makes_module_visible(complete):
    assert "os" in complete("import os\n|\n").names


# Spec: "`from os import *` makes all public names from `os` visible."
def test_star_import_exposes_public_names(complete):
    names = set(complete("from os import *\n|\n").names)
    assert {"getcwd", "sep", "path"} <= names
    assert not any(n.startswith("_") and n in names for n in ["_exit"])


# Spec: "Star imports resolve ... local project modules (files in the same directory)."
def test_star_import_of_a_local_module(complete, workdir):
    (workdir / "helpers.py").write_text(
        "LOCAL_CONST = 1\n"
        "def local_func():\n"
        "    pass\n"
        "class LocalClass:\n"
        "    pass\n"
        "_hidden = 2\n",
        encoding="utf-8",
    )
    result = complete("from helpers import *\n|\n")
    names = set(result.names)
    assert {"LOCAL_CONST", "local_func", "LocalClass"} <= names
    assert "_hidden" not in names
    assert result.by_name("local_func")["type"] == "function"
    assert result.by_name("LocalClass")["type"] == "class"


# Spec: "Star imports resolve both installed packages and local project modules."
def test_local_module_attribute_completion(complete, workdir):
    (workdir / "helpers.py").write_text(
        "def local_func():\n    pass\n_hidden = 1\n", encoding="utf-8"
    )
    result = complete("import helpers\nhelpers.|\n")
    assert "local_func" in result.names
    assert "_hidden" not in result.names


def test_from_local_module_import_name(complete, workdir):
    (workdir / "helpers.py").write_text("class LocalClass:\n    pass\n", encoding="utf-8")
    completion = complete("from helpers import LocalClass\nLocal|\n").by_name("LocalClass")
    assert completion["type"] == "class"


# Spec: "File does not exist or is not a regular file: exit 1, message to STDERR."
def test_missing_file_exits_one(workdir):
    result = run_cli("complete", str(workdir / "nope.py"), 1, 0)
    assert result.returncode == 1
    assert result.stderr.strip()


def test_directory_argument_exits_one(workdir):
    result = run_cli("complete", str(workdir), 1, 0)
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "File is not valid UTF-8: exit 1."
def test_invalid_utf8_exits_one(workdir):
    path = workdir / "bad.py"
    path.write_bytes(b"x = '\xff\xfe'\n")
    result = run_cli("complete", str(path), 1, 0)
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "Python syntax errors in the source file: do not exit with an error."
def test_syntax_error_still_exits_zero(complete):
    source = "def broken(:\n    pass\nalpha = 1\nalph|\n"
    result = complete(source)
    assert result.returncode == 0


# Spec: "Parse as much as possible and provide completions based on what was successfully
#        parsed."
def test_names_around_a_syntax_error_are_still_offered(complete):
    source = "good_one = 1\nthis is not python(((\ngood_two = 2\ngood|\n"
    names = set(complete(source).names)
    assert {"good_one", "good_two"} <= names


# Spec: the trailing incomplete line under the cursor is itself a syntax error.
def test_incomplete_attribute_line_at_cursor(complete):
    source = "import os\n\n\ndef f():\n    value = os.|\n"
    assert "getcwd" in complete(source).names


def test_incomplete_name_line_at_cursor(complete):
    source = "alpha = 1\n\n\ndef f():\n    x = al|\n"
    assert "alpha" in complete(source).names


# Spec: an empty file is still a valid target at line 1, column 0.
def test_empty_file_position_is_valid(complete):
    result = complete("", line=1, col=0)
    assert result.returncode == 0
    assert "print" in result.names
