"""The `rename` command applied to a module or package name."""


# "Renaming a module `foo` renames `foo.py` to `<new_name>.py`."
def test_module_file_is_renamed(rename):
    source = "import fo|o\n\nprint(foo.helper())\n"
    files = {"foo.py": "def helper():\n    return 1\n"}
    result = rename(source, files=files, new_name="bar")
    assert result.renames == {"foo.py": "bar.py"}


# "`renames` | object | Map of old path to new path, for file/directory renames"
def test_renames_uses_paths_relative_to_the_project_root(rename):
    source = "import pkg.fo|o\n"
    files = {"pkg/__init__.py": "", "pkg/foo.py": "value = 1\n"}
    result = rename(source, files=files, new_name="bar")
    assert result.renames == {"pkg/foo.py": "pkg/bar.py"}


# "All import statements referencing the old name are updated."
def test_plain_import_is_updated(rename):
    source = "import fo|o\n\nprint(foo.helper())\n"
    files = {"foo.py": "def helper():\n    return 1\n"}
    changed = rename(source, files=files, new_name="bar").changed_files
    assert changed["sample.py"] == "import bar\n\nprint(bar.helper())\n"


def test_from_import_is_updated(rename):
    source = "from fo|o import helper\n\nprint(helper())\n"
    files = {"foo.py": "def helper():\n    return 1\n"}
    changed = rename(source, files=files, new_name="bar").changed_files
    assert changed["sample.py"] == "from bar import helper\n\nprint(helper())\n"


def test_imports_in_every_file_are_updated(rename):
    source = "import fo|o\n"
    files = {"foo.py": "value = 1\n", "other.py": "from foo import value\n"}
    changed = rename(source, files=files, new_name="bar").changed_files
    assert changed["other.py"] == "from bar import value\n"


def test_a_dotted_import_keeps_its_package(rename):
    source = "import pkg.fo|o\n\nprint(pkg.foo.value)\n"
    files = {"pkg/__init__.py": "", "pkg/foo.py": "value = 1\n"}
    changed = rename(source, files=files, new_name="bar").changed_files
    assert changed["sample.py"] == "import pkg.bar\n\nprint(pkg.bar.value)\n"


def test_an_aliased_import_keeps_its_alias(rename):
    source = "import fo|o as f\n\nprint(f.value)\n"
    files = {"foo.py": "value = 1\n"}
    changed = rename(source, files=files, new_name="bar").changed_files
    assert changed["sample.py"] == "import bar as f\n\nprint(f.value)\n"


# "Renaming a package `foo` (directory with `__init__.py`) renames the directory."
def test_package_directory_is_renamed(rename):
    source = "import pa|ck\n"
    files = {"pack/__init__.py": "value = 1\n"}
    result = rename(source, files=files, new_name="crate")
    assert result.renames == {"pack": "crate"}


def test_imports_of_a_renamed_package_are_updated(rename):
    source = "import pa|ck\n\nprint(pack.value)\n"
    files = {"pack/__init__.py": "value = 1\n"}
    changed = rename(source, files=files, new_name="crate").changed_files
    assert changed["sample.py"] == "import crate\n\nprint(crate.value)\n"


def test_imports_of_a_module_inside_a_renamed_package_are_updated(rename):
    source = "from pa|ck.tools import helper\n"
    files = {"pack/__init__.py": "", "pack/tools.py": "def helper():\n    pass\n"}
    changed = rename(source, files=files, new_name="crate").changed_files
    assert changed["sample.py"] == "from crate.tools import helper\n"


# "If the cursor is on a module name (in an import or on the module's own
#  definition), the file or directory is renamed"
def test_cursor_on_a_module_use_renames_the_file(rename):
    source = "import foo\n\nprint(fo|o.value)\n"
    files = {"foo.py": "value = 1\n"}
    result = rename(source, files=files, new_name="bar")
    assert result.renames == {"foo.py": "bar.py"}
    assert result.changed_files["sample.py"] == "import bar\n\nprint(bar.value)\n"


# "If the new name would collide with an existing name in scope, exit 1"
def test_renaming_onto_an_existing_module_is_rejected(rename):
    source = "import fo|o\n"
    files = {"foo.py": "value = 1\n", "bar.py": "other = 2\n"}
    result = rename(source, files=files, new_name="bar", expect_ok=False)
    assert result.returncode == 1
    assert result.stdout == ""


# "`--new-name` must be a valid Python identifier. If not, exit 1."
def test_an_invalid_module_name_is_rejected(rename):
    source = "import fo|o\n"
    files = {"foo.py": "value = 1\n"}
    assert rename(source, files=files, new_name="not-a-name", expect_ok=False).returncode == 1


# "With `--diff`, output is plain text to STDOUT (not JSON)."
def test_module_rename_diff_is_plain_text(rename):
    source = "import fo|o\n\nprint(foo.value)\n"
    files = {"foo.py": "value = 1\n"}
    stdout = rename(source, files=files, new_name="bar", diff=True).stdout
    assert not stdout.startswith("{")
    assert "-import foo" in stdout
    assert "+import bar" in stdout


def test_a_relative_import_of_the_module_is_updated(rename):
    source = "import pack.tools\n"
    files = {
        "pack/__init__.py": "",
        "pack/tools.py": "value = 1\n",
        "pack/user.py": "from .tools import value\n",
    }
    changed = rename(source, cursor=(1, 12), files=files, new_name="kit").changed_files
    assert changed["pack/user.py"] == "from .kit import value\n"


def test_a_module_imported_as_a_member_is_updated(rename):
    source = "from pack import to|ols\n\nprint(tools.value)\n"
    files = {"pack/__init__.py": "", "pack/tools.py": "value = 1\n"}
    result = rename(source, files=files, new_name="kit")
    assert result.renames == {"pack/tools.py": "pack/kit.py"}
    assert result.changed_files["sample.py"] == "from pack import kit\n\nprint(kit.value)\n"
