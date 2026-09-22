"""Attribute completion for names that were imported from another file."""

WIDGET = (
    "class Widget:\n"
    "    def __init__(self):\n"
    "        self.size = 1\n"
    "\n"
    "    def resize(self):\n"
    "        return 1\n"
    "\n"
    "    def _internal(self):\n"
    "        return 2\n"
    "\n"
    "\n"
    "def build():\n"
    "    return Widget()\n"
)


# Spec: "Attribute completion now works for imported names"
def test_completion_on_an_imported_class(complete):
    names = complete("from helpers import Widget\nWidget.|\n", files={"helpers.py": WIDGET}).names
    assert "resize" in names


def test_completion_on_an_instance_of_an_imported_class(complete):
    source = "from helpers import Widget\nw = Widget()\nw.|\n"
    names = complete(source, files={"helpers.py": WIDGET}).names
    assert {"resize", "size"} <= set(names)


# Spec: "Attribute completion now works for imported names" -- through a call, too.
def test_completion_on_an_imported_factory_result(complete):
    source = "from helpers import build\nw = build()\nw.|\n"
    assert "resize" in complete(source, files={"helpers.py": WIDGET}).names


# Spec: cross-file completion reaches through a package.
def test_completion_through_a_package(complete):
    files = {"pkg/__init__.py": "", "pkg/tools.py": WIDGET}
    source = "from pkg.tools import Widget\nw = Widget()\nw.|\n"
    assert "resize" in complete(source, files=files).names


# Spec: cross-file completion reaches through a chain of imports.
def test_completion_through_an_import_chain(complete):
    files = {"middle.py": "from base import Widget\n", "base.py": WIDGET}
    source = "from middle import Widget\nw = Widget()\nw.|\n"
    assert "resize" in complete(source, files=files).names


# Spec: "... completions return nothing for that module's attributes."
def test_completion_on_a_name_from_a_missing_module(complete):
    assert complete("from nowhere_at_all import Widget\nWidget.|\n").completions == []


# Spec: module attribute completion still lists the module's public names.
def test_module_attribute_completion(complete):
    result = complete("import helpers\nhelpers.|\n", files={"helpers.py": WIDGET})
    assert {"Widget", "build"} <= set(result.names)


# Spec: a package exposes its submodules as attributes.
def test_package_attribute_completion_lists_submodules(complete):
    files = {"pkg/__init__.py": "ROOT = 1\n", "pkg/tools.py": WIDGET}
    names = set(complete("import pkg\npkg.|\n", files=files).names)
    assert {"ROOT", "tools"} <= names


# Spec: "goto returns where the name at the cursor is defined" -- attribute of an import.
def test_goto_an_attribute_of_an_imported_class(goto):
    source = "from helpers import Widget\nWidget.res|ize\n"
    definition = goto(source, files={"helpers.py": WIDGET}).only
    assert (definition["module_path"], definition["line"]) == ("helpers.py", 5)
