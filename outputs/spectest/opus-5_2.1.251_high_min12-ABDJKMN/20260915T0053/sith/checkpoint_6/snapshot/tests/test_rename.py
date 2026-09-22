"""Spec section: the `rename` subcommand."""
import json

import pytest

from conftest import CURSOR, rename_raw, rename_in, changed, run_raw

C = CURSOR


# --- Phrase: "python sith.py rename <file> <line> <col> --new-name <name>
#     [--diff] [--project <dir>]" — the command exists and exits 0.
def test_rename_command_exists(tmp_path):
    proc = rename_raw(tmp_path, {"example.py": "val" + C + "ue = 1\n"}, "total")
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout)


# --- Phrase: field "changed_files | object | Map of file path (relative to
#     project root) to new file content."
def test_changed_files_is_path_to_content(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    data = rename_in(tmp_path, files, "total")
    assert changed(data) == {"example.py": "total = 1\nprint(total)\n"}


# --- Phrase: field "renames | object | Map of old path to new path ... Empty
#     if no paths changed."
def test_renames_empty_for_a_plain_rename(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    data = rename_in(tmp_path, files, "total")
    assert data["renames"] == {}


# --- Phrase: the payload carries exactly the two documented fields.
def test_rename_payload_fields(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    data = rename_in(tmp_path, files, "total")
    assert set(data) == {"changed_files", "renames"}


# --- Phrase: "Rename the name at the cursor and all its references across the
#     project."
def test_rename_crosses_files(tmp_path):
    files = {
        "lib.py": "def hel" + C + "per():\n    return 1\n",
        "main.py": "from lib import helper\n\nprint(helper())\n",
    }
    data = rename_in(tmp_path, files, "worker")
    assert changed(data) == {
        "lib.py": "def worker():\n    return 1\n",
        "main.py": "from lib import worker\n\nprint(worker())\n",
    }


# --- Phrase: "Only files that actually changed are included."
def test_unchanged_files_are_absent(tmp_path):
    files = {
        "example.py": "val" + C + "ue = 1\nprint(value)\n",
        "other.py": "unrelated = 2\n",
    }
    data = rename_in(tmp_path, files, "total")
    assert list(changed(data)) == ["example.py"]


# --- Phrase: "Rename scope: All references found via the same logic as
#     `references --scope project` are renamed."
def test_rename_only_touches_the_same_symbol(tmp_path):
    code = (
        "def outer():\n"
        "    value = 1\n"
        "    return value\n"
        "\n"
        "\n"
        "val" + C + "ue = 2\n"
        "print(value)\n"
    )
    data = rename_in(tmp_path, {"example.py": code}, "total")
    assert "    value = 1" in changed(data)["example.py"]
    assert "total = 2" in changed(data)["example.py"]


def test_rename_matches_references_scope_project(tmp_path):
    files = {
        "lib.py": "count = 0\n",
        "main.py": "from lib import cou" + C + "nt\n\nprint(count)\n",
    }
    data = rename_in(tmp_path, files, "total")
    assert changed(data) == {
        "lib.py": "total = 0\n",
        "main.py": "from lib import total\n\nprint(total)\n",
    }


# --- Phrase: "Module renames: ... Renaming a module `foo` renames `foo.py` to
#     `<new_name>.py`."
def test_module_rename_moves_the_file(tmp_path):
    files = {
        "foo.py": "thing = 1\n",
        "main.py": "import fo" + C + "o\n\nprint(foo.thing)\n",
    }
    data = rename_in(tmp_path, files, "bar")
    assert data["renames"] == {"foo.py": "bar.py"}


# --- Phrase: "All import statements referencing the old name are updated."
def test_module_rename_updates_imports(tmp_path):
    files = {
        "foo.py": "thing = 1\n",
        "main.py": "import fo" + C + "o\n\nprint(foo.thing)\n",
    }
    data = rename_in(tmp_path, files, "bar")
    assert changed(data) == {"main.py": "import bar\n\nprint(bar.thing)\n"}


def test_module_rename_updates_from_imports(tmp_path):
    files = {
        "foo.py": "thing = 1\n",
        "main.py": "from fo" + C + "o import thing\n\nprint(thing)\n",
    }
    data = rename_in(tmp_path, files, "bar")
    assert data["renames"] == {"foo.py": "bar.py"}
    assert changed(data) == {"main.py": "from bar import thing\n\nprint(thing)\n"}


# --- Phrase: "Renaming a package `foo` (directory with `__init__.py`) renames
#     the directory."
def test_package_rename_moves_the_directory(tmp_path):
    files = {
        "pkg/__init__.py": "value = 1\n",
        "main.py": "import pk" + C + "g\n\nprint(pkg.value)\n",
    }
    data = rename_in(tmp_path, files, "core")
    assert data["renames"] == {"pkg": "core"}
    assert changed(data) == {"main.py": "import core\n\nprint(core.value)\n"}


def test_package_rename_updates_submodule_imports(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/sub.py": "thing = 1\n",
        "main.py": "from pk" + C + "g.sub import thing\n",
    }
    data = rename_in(tmp_path, files, "core")
    assert data["renames"] == {"pkg": "core"}
    assert changed(data) == {"main.py": "from core.sub import thing\n"}


# --- Phrase: "Validation: `--new-name` must be a valid Python identifier. If
#     not, exit 1."
@pytest.mark.parametrize("bad", ["2bad", "with space", "", "a-b", "x.y"])
def test_invalid_new_name_exits_1(tmp_path, bad):
    proc = rename_raw(tmp_path, {"example.py": "val" + C + "ue = 1\n"}, bad)
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "Validation: If the cursor is not on a name, exit 1."
def test_cursor_not_on_a_name_exits_1(tmp_path):
    proc = rename_raw(tmp_path, {"example.py": "value = " + C + "1\n"}, "total")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_cursor_on_a_keyword_exits_1(tmp_path):
    code = "if" + C + " True:\n    pass\n"
    proc = rename_raw(tmp_path, {"example.py": code}, "total")
    assert proc.returncode == 1


# --- Phrase: "If the new name would collide with an existing name in scope,
#     exit 1 with a descriptive message."
def test_collision_exits_1_with_a_message(tmp_path):
    code = (
        "def fir" + C + "st():\n"
        "    pass\n"
        "\n"
        "\n"
        "def second():\n"
        "    pass\n"
    )
    proc = rename_raw(tmp_path, {"example.py": code}, "second")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "second" in proc.stderr


def test_collision_inside_a_function_scope(tmp_path):
    code = (
        "def outer():\n"
        "    val" + C + "ue = 1\n"
        "    other = 2\n"
        "    return value + other\n"
    )
    proc = rename_raw(tmp_path, {"example.py": code}, "other")
    assert proc.returncode == 1
    assert proc.stderr.strip() != ""


def test_shadowing_an_outer_name_is_not_a_collision(tmp_path):
    code = (
        "outside = 1\n"
        "\n"
        "\n"
        "def outer():\n"
        "    val" + C + "ue = 2\n"
        "    return value\n"
    )
    proc = rename_raw(tmp_path, {"example.py": code}, "outside")
    assert proc.returncode == 0, proc.stderr


# --- Phrase (T110): renaming a name with no references beyond its definition
#     still succeeds.
def test_rename_with_no_other_references(tmp_path):
    data = rename_in(tmp_path, {"example.py": "unu" + C + "sed = 1\n"}, "spare")
    assert changed(data) == {"example.py": "spare = 1\n"}


# --- Phrase: "[--project <dir>]" — paths are relative to the project root.
def test_project_flag_sets_the_path_root(tmp_path):
    files = {
        "src/lib.py": "def hel" + C + "per():\n    return 1\n",
        "src/main.py": "from lib import helper\n\nprint(helper())\n",
    }
    data = rename_in(tmp_path, files, "worker", project=tmp_path / "src")
    assert sorted(changed(data)) == ["lib.py", "main.py"]


# --- Phrase: a missing file is a tool-level failure.
def test_missing_file_exits_1(tmp_path):
    proc = run_raw("rename", str(tmp_path / "nope.py"), 1, 0,
                   "--new-name", "x", cwd=str(tmp_path))
    assert proc.returncode == 1
