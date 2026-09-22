"""The `rename` command: renaming a name and every reference to it."""

from conftest import run_cli


# "python sith.py rename <file> <line> <col> --new-name <name>"
def test_rename_accepts_file_line_col_and_new_name(rename):
    result = rename("va|lue = 1\nprint(value)\n", new_name="total")
    assert result.returncode == 0


# "Rename the name at the cursor and all its references across the project."
def test_definition_and_references_are_renamed(rename):
    changed = rename("va|lue = 1\nprint(value)\n", new_name="total").changed_files
    assert changed["sample.py"] == "total = 1\nprint(total)\n"


def test_rename_from_a_reference_renames_the_definition(rename):
    changed = rename("value = 1\nprint(val|ue)\n", new_name="total").changed_files
    assert changed["sample.py"] == "total = 1\nprint(total)\n"


def test_function_name_and_call_sites_are_renamed(rename):
    source = "def he|lper(a):\n    return a\n\n\nprint(helper(1))\n"
    changed = rename(source, new_name="worker").changed_files
    assert changed["sample.py"] == "def worker(a):\n    return a\n\n\nprint(worker(1))\n"


# "All references found via the same logic as `references --scope project` are renamed."
def test_references_in_other_files_are_renamed(rename):
    source = "def he|lper(a):\n    return a\n"
    files = {"main.py": "from sample import helper\n\nprint(helper(1))\n"}
    changed = rename(source, files=files, new_name="worker").changed_files
    assert changed["main.py"] == "from sample import worker\n\nprint(worker(1))\n"
    assert changed["sample.py"] == "def worker(a):\n    return a\n"


def test_an_unrelated_name_spelled_the_same_is_left_alone(rename):
    source = "def f():\n    value = 1\n    return va|lue\n\n\nvalue = 2\n"
    changed = rename(source, new_name="total").changed_files
    assert changed["sample.py"].endswith("value = 2\n")
    assert "    total = 1\n" in changed["sample.py"]


def test_attribute_references_are_renamed(rename):
    source = "class C:\n    def me|thod(self):\n        return 1\n\n\nC().method()\n"
    changed = rename(source, new_name="run").changed_files
    assert changed["sample.py"].endswith("C().run()\n")
    assert "    def run(self):\n" in changed["sample.py"]


# "`changed_files` | object | Map of file path (relative to project root) to new file content."
def test_changed_file_keys_are_relative_to_the_project_root(rename):
    source = "va|lue = 1\nprint(value)\n"
    changed = rename(source, path="pkg/mod.py", files={"pkg/__init__.py": ""},
                     new_name="total").changed_files
    assert list(changed) == ["pkg/mod.py"]


# "Only files that actually changed are included."
def test_untouched_files_are_not_reported(rename):
    source = "va|lue = 1\nprint(value)\n"
    changed = rename(source, files={"other.py": "x = 2\n"}, new_name="total").changed_files
    assert list(changed) == ["sample.py"]


# "`renames` | object | ... Empty if no paths changed."
def test_renames_is_empty_for_an_ordinary_rename(rename):
    assert rename("va|lue = 1\nprint(value)\n", new_name="total").renames == {}


# "Output ... changed_files (JSON)"
def test_payload_has_changed_files_and_renames(rename):
    payload = rename("va|lue = 1\nprint(value)\n", new_name="total").payload
    assert set(payload) == {"changed_files", "renames"}


# "**Validation:** `--new-name` must be a valid Python identifier. If not, exit 1."
def test_an_invalid_identifier_is_rejected(rename):
    result = rename("va|lue = 1\n", new_name="not a name", expect_ok=False)
    assert result.returncode == 1


def test_a_keyword_is_not_a_valid_new_name(rename):
    result = rename("va|lue = 1\n", new_name="class", expect_ok=False)
    assert result.returncode == 1


def test_a_digit_leading_new_name_is_rejected(rename):
    result = rename("va|lue = 1\n", new_name="2total", expect_ok=False)
    assert result.returncode == 1


# "Validation failures ... exit 1 and must not emit partial edit output."
def test_a_rejected_name_prints_nothing_on_stdout(rename):
    result = rename("va|lue = 1\nprint(value)\n", new_name="1bad", expect_ok=False)
    assert result.stdout == ""
    assert result.stderr.strip() != ""


# "If the cursor is not on a name, exit 1."
def test_cursor_on_whitespace_is_rejected(rename):
    result = rename("value = 1\n   |   \n", new_name="total", expect_ok=False)
    assert result.returncode == 1


def test_cursor_on_an_operator_is_rejected(rename):
    result = rename("value =| 1\n", new_name="total", expect_ok=False)
    assert result.returncode == 1


def test_cursor_on_a_literal_is_rejected(rename):
    result = rename("value = 1|23\n", new_name="total", expect_ok=False)
    assert result.returncode == 1


# "If the new name would collide with an existing name in scope, exit 1 with a
#  descriptive message."
def test_collision_with_a_sibling_definition_is_rejected(rename):
    source = "def fi|rst():\n    pass\n\n\ndef second():\n    pass\n"
    result = rename(source, new_name="second", expect_ok=False)
    assert result.returncode == 1
    assert "second" in result.stderr


def test_collision_with_a_local_in_the_same_function_is_rejected(rename):
    source = "def f():\n    va|lue = 1\n    other = 2\n    return value + other\n"
    result = rename(source, new_name="other", expect_ok=False)
    assert result.returncode == 1


def test_a_collision_emits_no_edits(rename):
    source = "def fi|rst():\n    pass\n\n\ndef second():\n    pass\n"
    assert rename(source, new_name="second", expect_ok=False).stdout == ""


def test_a_name_used_in_another_scope_is_not_a_collision(rename):
    source = "def f():\n    va|lue = 1\n    return value\n\n\ndef g():\n    other = 2\n"
    changed = rename(source, new_name="other").changed_files
    assert "    other = 1\n" in changed["sample.py"]


# "**With `--diff`:** Output a unified diff instead of full file contents"
def test_diff_output_is_not_json(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total", diff=True).stdout
    assert not stdout.startswith("{")


def test_diff_shows_removed_and_added_lines(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total", diff=True).stdout
    assert "-value = 1" in stdout
    assert "+total = 1" in stdout


def test_diff_has_a_hunk_header(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total", diff=True).stdout
    assert "@@" in stdout


def test_diff_names_each_changed_file(rename):
    source = "def he|lper():\n    pass\n"
    files = {"main.py": "from sample import helper\n\nhelper()\n"}
    stdout = rename(source, files=files, new_name="worker", diff=True).stdout
    assert "--- main.py" in stdout
    assert "+++ main.py" in stdout
    assert "--- sample.py" in stdout


# "[--project <dir>]" selects the tree that is searched and the paths reported.
def test_project_option_scopes_the_search(rename):
    source = "def he|lper():\n    pass\n"
    files = {"pkg/__init__.py": "", "pkg/user.py": "from sample import helper\n"}
    changed = rename(source, files=files, new_name="worker").changed_files
    assert "pkg/user.py" in changed


# "On error, print a message to STDERR and exit 1."
def test_rename_on_a_missing_file_fails(workdir):
    result = run_cli("rename", str(workdir / "missing.py"), 1, 0, "--new-name", "x")
    assert result.returncode == 1
    assert result.stdout == ""


def test_new_name_is_required(workdir, rename):
    result = rename("va|lue = 1\n", expect_ok=False)
    assert result.returncode == 1
