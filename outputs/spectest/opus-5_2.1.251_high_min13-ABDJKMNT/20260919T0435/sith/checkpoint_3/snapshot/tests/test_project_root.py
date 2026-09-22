"""The `--project` flag and what the project root decides."""

HELPERS = 'class Widget:\n    """A widget."""\n'


# Spec: "All commands now accept an optional `--project <dir>` flag."
def test_project_flag_accepted_by_every_command(navigate, complete, workdir):
    files = {"helpers.py": HELPERS, "pkg/__init__.py": ""}
    source = "import helpers\nhelp|ers\n"
    for command in ("infer", "goto"):
        result = navigate(command, source, name="pkg/app.py", files=files, project=".")
        assert result.returncode == 0, result.stderr
    result = complete("import helpers\nhelpers.|\n", name="pkg/app.py", files=files, project=".")
    assert result.returncode == 0, result.stderr


# Spec: "When provided, the project root is `<dir>`." / "Where to search for modules
#        when resolving imports."
def test_project_flag_sets_the_module_search_root(infer):
    files = {"helpers.py": HELPERS, "pkg/__init__.py": ""}
    source = "from helpers import Widget\nWid|get\n"
    definition = infer(source, name="pkg/app.py", files=files, project=".").only
    assert definition["name"] == "Widget"
    assert definition["module_path"] == "helpers.py"


# Spec: "When omitted, the project root is the directory containing `<file>`."
def test_without_the_flag_the_root_is_the_files_directory(infer):
    files = {"helpers.py": HELPERS, "pkg/__init__.py": ""}
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, name="pkg/app.py", files=files).definitions == []


# Spec: "When omitted, the project root is the directory containing `<file>`."
def test_sibling_module_resolves_without_the_flag(infer):
    source = "from helpers import Widget\nWid|get\n"
    definition = infer(source, files={"helpers.py": HELPERS}).only
    assert definition["module_path"] == "helpers.py"


# Spec: "The base for computing module qualified names."
def test_qualified_name_is_relative_to_the_project_root(infer):
    source = 'class Widget:\n    """W."""\n\nw = Widget()\n|w\n'
    definition = infer(source, name="pkg/app.py", files={"pkg/__init__.py": ""}, project=".").only
    assert definition["full_name"] == "pkg.app.Widget"
    assert definition["module_path"] == "pkg/app.py"


# Spec: "The base for computing module qualified names."
def test_qualified_name_without_the_flag_drops_the_package(infer):
    source = 'class Widget:\n    """W."""\n\nw = Widget()\n|w\n'
    definition = infer(source, name="pkg/app.py", files={"pkg/__init__.py": ""}).only
    assert definition["full_name"] == "app.Widget"
    assert definition["module_path"] == "app.py"


# Spec: "The base for computing module qualified names." -- for an imported module too.
def test_imported_module_qualified_name(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": "class Widget:\n    pass\n"}
    source = "from pkg.tools import Widget\nWid|get\n"
    definition = infer(source, files=files).only
    assert definition["full_name"] == "pkg.tools.Widget"
    assert definition["module_path"] == "pkg/tools.py"


# Spec: a package `__init__.py` is named after the package itself.
def test_package_init_qualified_name(infer):
    files = {"pkg/__init__.py": "class Widget:\n    pass\n"}
    source = "from pkg import Widget\nWid|get\n"
    definition = infer(source, files=files).only
    assert definition["full_name"] == "pkg.Widget"
    assert definition["module_path"] == "pkg/__init__.py"
