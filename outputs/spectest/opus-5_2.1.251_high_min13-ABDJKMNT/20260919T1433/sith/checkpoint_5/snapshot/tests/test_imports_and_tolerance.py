"""Spec: import visibility, star imports, and syntax-error tolerance."""


# Spec: "`import os` makes `os` visible as a module."
def test_plain_import_is_visible_as_module(complete):
    item = complete("import os\no$\n").by_name("os")
    assert item["type"] == "module"


# Spec: a dotted import binds its first component.
def test_dotted_import_binds_root_package(complete):
    names = complete("import os.path\no$\n").names
    assert "os" in names


# Spec: "`from os import *` makes all public names from `os` visible."
def test_star_import_exposes_public_names(complete):
    names = complete("from os import *\n$\n").names
    assert {"getcwd", "sep", "path"} <= set(names)


def test_star_import_hides_private_names(complete):
    source = "from os import *\n_$\n"
    names = complete(source).names
    assert "_exit" not in names


def test_star_imported_names_keep_their_kind(complete):
    result = complete("from os import *\ngetcw$\n")
    assert result.by_name("getcwd")["type"] == "function"


# Spec: "Star imports resolve both installed packages and local project
# modules (files in the same directory)."
def test_star_import_of_local_module(complete):
    helper = (
        "LOCAL_CONSTANT = 3\n"
        "def local_function():\n"
        "    pass\n"
        "class LocalClass:\n"
        "    pass\n"
        "_hidden = 1\n"
    )
    result = complete(
        "from helper_module import *\n$\n", extra={"helper_module.py": helper}
    )
    names = result.names
    assert {"LOCAL_CONSTANT", "local_function", "LocalClass"} <= set(names)
    assert "_hidden" not in names
    assert result.by_name("local_function")["type"] == "function"
    assert result.by_name("LocalClass")["type"] == "class"


# Spec: local modules are also receivers for attribute completion.
def test_local_module_attributes(complete):
    helper = "def local_function():\n    pass\n"
    result = complete(
        "import helper_module\nhelper_module.$\n", extra={"helper_module.py": helper}
    )
    assert "local_function" in result.names


# Spec: "Python syntax errors in the source file: do not exit with an error."
def test_syntax_error_still_exits_zero(complete):
    source = "def broken(:\n    pass\nvalue = 1\n$\n"
    assert complete(source).code == 0


# Spec: "Parse as much as possible and provide completions based on what was
# successfully parsed."
def test_completions_survive_a_broken_line(complete):
    source = (
        "good_value = 1\n"
        "def broken(:\n"
        "    pass\n"
        "later_value = 2\n"
        "$\n"
    )
    names = complete(source).names
    assert "good_value" in names


# Spec: the cursor line itself is usually not valid Python while typing.
def test_incomplete_attribute_line_is_tolerated(complete):
    source = "import os\nresult = os.$\n"
    result = complete(source)
    assert result.code == 0
    assert "getcwd" in result.names


def test_incomplete_line_inside_function_is_tolerated(complete):
    source = (
        "def user():\n"
        "    text = 'value'\n"
        "    text.$\n"
    )
    assert "upper" in complete(source).names


def test_completion_on_trailing_blank_line_of_a_function(complete):
    source = "def user():\n    inner_value = 1\n    $\n"
    assert "inner_value" in complete(source).names


def test_broken_function_body_keeps_module_names(complete):
    source = (
        "module_value = 1\n"
        "def user():\n"
        "    os.\n"
        "modu$\n"
    )
    assert "module_value" in complete(source).names
