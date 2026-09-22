"""Spec: New Subcommands / `rename`."""

import json


# Spec: "python sith.py rename <file> <line> <col> --new-name <name>"
def test_rename_subcommand_is_accepted(rename):
    result = rename("def hel$per():\n    pass\n", "worker")
    assert result.code == 0


# Spec: "Rename the name at the cursor and all its references across the project."
def test_definition_and_its_uses_are_renamed(rename):
    result = rename("def hel$per():\n    pass\n\nhelper()\n", "worker")
    assert result.changed_files == {
        "module_under_test.py": "def worker():\n    pass\n\nworker()\n"
    }


# Spec: "Rename the name at the cursor" - the cursor may sit on a use of it.
def test_rename_started_from_a_use(rename):
    result = rename("def helper():\n    pass\n\nhel$per()\n", "worker")
    assert result.changed_files == {
        "module_under_test.py": "def worker():\n    pass\n\nworker()\n"
    }


# Spec: "and all its references across the project"
def test_references_in_other_files_are_renamed(rename):
    extra = {"library.py": "def helper():\n    pass\n"}
    result = rename("from library import hel$per\n\nhelper()\n", "worker", extra=extra)
    assert result.changed_files == {
        "library.py": "def worker():\n    pass\n",
        "module_under_test.py": "from library import worker\n\nworker()\n",
    }


# Spec: "`changed_files` | object | Map of file path (relative to project root) to
# new file content."
def test_changed_files_is_keyed_by_project_relative_path(rename):
    extra = {"package/library.py": "def helper():\n    pass\n"}
    result = rename("from package.library import hel$per\n", "worker", extra=extra)
    assert sorted(result.changed_files) == ["module_under_test.py", "package/library.py"]


# Spec: "Only files that actually changed are included."
def test_untouched_files_are_left_out(rename):
    extra = {"other.py": "unrelated = 1\n"}
    result = rename("def hel$per():\n    pass\n", "worker", extra=extra)
    assert list(result.changed_files) == ["module_under_test.py"]


# Spec: "`renames` | object | ... Empty if no paths changed."
def test_renames_is_empty_when_no_path_changed(rename):
    result = rename("def hel$per():\n    pass\n", "worker")
    assert result.renames == {}


# Spec: "Rename scope: All references found via the same logic as
# `references --scope project` are renamed."
def test_unrelated_name_spelled_the_same_is_untouched(rename):
    extra = {"other.py": "def helper():\n    pass\n\nhelper()\n"}
    result = rename("def hel$per():\n    pass\n\nhelper()\n", "worker", extra=extra)
    assert list(result.changed_files) == ["module_under_test.py"]


# Spec: "Renaming a module `foo` renames `foo.py` to `<new_name>.py`."
def test_module_rename_moves_the_file(rename):
    extra = {"helpers.py": "VALUE = 1\n"}
    result = rename("import hel$pers\n\nprint(helpers.VALUE)\n", "utilities", extra=extra)
    assert result.renames == {"helpers.py": "utilities.py"}


# Spec: "All import statements referencing the old name are updated."
def test_module_rename_updates_imports_and_uses(rename):
    extra = {"helpers.py": "VALUE = 1\n"}
    result = rename("import hel$pers\n\nprint(helpers.VALUE)\n", "utilities", extra=extra)
    assert result.changed_files == {
        "module_under_test.py": "import utilities\n\nprint(utilities.VALUE)\n"
    }


# Spec: "If the cursor is on a module name (in an import ...)"
def test_module_named_in_a_from_import_is_renamed(rename):
    extra = {"helpers.py": "VALUE = 1\n"}
    result = rename("from hel$pers import VALUE\n", "utilities", extra=extra)
    assert result.renames == {"helpers.py": "utilities.py"}
    assert result.changed_files == {"module_under_test.py": "from utilities import VALUE\n"}


# Spec: "Renaming a package `foo` (directory with `__init__.py`) renames the directory."
def test_package_rename_moves_the_directory(rename):
    extra = {"pack/__init__.py": "", "pack/inner.py": "VALUE = 1\n"}
    result = rename("from pac$k.inner import VALUE\n", "bundle", extra=extra)
    assert result.renames == {"pack": "bundle"}
    assert result.changed_files == {"module_under_test.py": "from bundle.inner import VALUE\n"}


# Spec: "Renaming a module `foo` ... All import statements referencing the old
# name are updated." - a submodule of a package keeps its package path.
def test_submodule_rename_keeps_the_package_path(rename):
    extra = {"pack/__init__.py": "", "pack/inner.py": "VALUE = 1\n"}
    result = rename("from pack.in$ner import VALUE\n", "core", extra=extra)
    assert result.renames == {"pack/inner.py": "pack/core.py"}
    assert result.changed_files == {"module_under_test.py": "from pack.core import VALUE\n"}


# Spec: "--new-name must be a valid Python identifier. If not, exit 1."
def test_invalid_new_name_exits_one(rename):
    result = rename("def hel$per():\n    pass\n", "not a name")
    assert result.code == 1
    assert result.stderr.strip()


# Spec: "Validation failures ... must not emit partial edit output."
def test_invalid_new_name_writes_nothing_to_stdout(rename):
    assert rename("def hel$per():\n    pass\n", "9lives").stdout == ""


# Spec: "If the cursor is not on a name, exit 1."
def test_cursor_off_a_name_exits_one(rename):
    result = rename("value = 1 $+ 2\n", "worker")
    assert result.code == 1
    assert result.stdout == ""


# Spec: "If the new name would collide with an existing name in scope, exit 1
# with a descriptive message."
def test_collision_in_the_same_scope_exits_one(rename):
    result = rename("def hel$per():\n    pass\n\ndef worker():\n    pass\n", "worker")
    assert result.code == 1
    assert "worker" in result.stderr
    assert result.stdout == ""


# Spec: "If the new name would collide with an existing name in scope, exit 1"
def test_collision_between_locals_exits_one(rename):
    source = "def outer():\n    val$ue = 1\n    other = 2\n    return value, other\n"
    assert rename(source, "other").code == 1


# Spec: "If the new name would collide ..." - a name bound in a different scope
# is not a collision.
def test_name_taken_in_another_scope_is_not_a_collision(rename):
    source = "def outer():\n    val$ue = 1\n    return value\n\ndef other():\n    taken = 2\n"
    assert rename(source, "taken").code == 0


# Spec: "With --diff, output is plain text to STDOUT (not JSON)."
def test_diff_output_is_not_json(rename):
    result = rename("def hel$per():\n    pass\n\nhelper()\n", "worker", diff=True)
    assert result.code == 0
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("diff output parsed as JSON")


# Spec: "With `--diff`: Output a unified diff instead of full file contents"
def test_diff_shows_removed_and_added_lines(rename):
    result = rename("def hel$per():\n    pass\n\nhelper()\n", "worker", diff=True)
    assert "-def helper():" in result.stdout
    assert "+def worker():" in result.stdout
    assert "@@" in result.stdout
