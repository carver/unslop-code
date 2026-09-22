"""Resolving absolute and relative imports to files in the project."""

WIDGET = 'class Widget:\n    """A widget."""\n\n    def resize(self):\n        return 1\n'


# Spec: "Project root -- scan for `.py` files ... "
def test_absolute_import_of_a_project_file(infer):
    source = "from helpers import Widget\nWid|get\n"
    definition = infer(source, files={"helpers.py": WIDGET}).only
    assert (definition["module_path"], definition["line"]) == ("helpers.py", 1)


# Spec: "... and packages (directories containing `__init__.py`)."
def test_absolute_import_of_a_package_submodule(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": WIDGET}
    definition = infer("from pkg.tools import Widget\nWid|get\n", files=files).only
    assert definition["module_path"] == "pkg/tools.py"


# Spec: "... and packages (directories containing `__init__.py`)."
def test_dotted_module_attribute_access(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": WIDGET}
    definition = infer("import pkg.tools\npkg.tools.Wid|get\n", files=files).only
    assert definition["module_path"] == "pkg/tools.py"


# Spec: "The same import rules apply to regular packages and namespace packages."
def test_namespace_package_without_init(infer):
    files = {"space/tools.py": WIDGET}
    definition = infer("from space.tools import Widget\nWid|get\n", files=files).only
    assert definition["module_path"] == "space/tools.py"


# Spec: "Standard library -- recognize stdlib modules available in the target runtime."
def test_stdlib_module_is_recognized(complete):
    assert "getcwd" in complete("import os\nos.|\n").names


# Spec: search order -- "1. Project root" comes before "2. Standard library".
def test_project_module_shadows_the_stdlib(complete):
    files = {"json.py": "def project_only():\n    pass\n"}
    names = complete("import json\njson.|\n", files=files).names
    assert "project_only" in names
    assert "dumps" not in names


# Spec: "If a module cannot be found, treat it as unresolvable -- `infer` and `goto`
#        return empty results, completions return nothing for that module's attributes."
def test_unresolvable_module_infers_to_nothing(infer):
    assert infer("import nowhere_at_all\nnowhere_at_|all\n").definitions == []


def test_unresolvable_module_completes_to_nothing(complete):
    assert complete("import nowhere_at_all\nnowhere_at_all.|\n").completions == []


def test_unresolvable_member_infers_to_nothing(infer):
    assert infer("from nowhere_at_all import thing\nthi|ng\n").definitions == []


# Spec: relative imports resolve against the importing module's package.
def test_relative_import_from_the_same_package(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": WIDGET}
    source = "from .tools import Widget\nWid|get\n"
    definition = infer(source, name="pkg/app.py", files=files, project=".").only
    assert definition["module_path"] == "pkg/tools.py"


# Spec: relative imports -- `from . import <module>` names a sibling module.
def test_relative_import_of_a_sibling_module(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": WIDGET}
    source = "from . import tools\ntools.Wid|get\n"
    definition = infer(source, name="pkg/app.py", files=files, project=".").only
    assert definition["module_path"] == "pkg/tools.py"


# Spec: a two-dot import climbs one package.
def test_relative_import_from_the_parent_package(infer):
    files = {"pkg/__init__.py": "", "pkg/inner/__init__.py": "", "pkg/tools.py": WIDGET}
    source = "from ..tools import Widget\nWid|get\n"
    definition = infer(source, name="pkg/inner/app.py", files=files, project=".").only
    assert definition["module_path"] == "pkg/tools.py"


# Spec: two dots from a package directly under the root name the root itself.
def test_relative_import_reaching_the_project_root(infer):
    files = {"pkg/__init__.py": "", "helpers.py": WIDGET}
    source = "from ..helpers import Widget\nWid|get\n"
    definition = infer(source, name="pkg/app.py", files=files, project=".").only
    assert definition["module_path"] == "helpers.py"


# Spec: "If the relative import goes above the project root, it is unresolvable."
def test_relative_import_above_the_project_root(infer):
    files = {"pkg/__init__.py": "", "helpers.py": WIDGET}
    source = "from ...helpers import Widget\nWid|get\n"
    assert infer(source, name="pkg/app.py", files=files, project=".").definitions == []


# Spec: "If the relative import goes above the project root, it is unresolvable."
def test_relative_import_above_the_root_from_a_root_module(infer):
    source = "from ..helpers import Widget\nWid|get\n"
    assert infer(source, files={"helpers.py": WIDGET}).definitions == []


# Spec: "If the relative import goes above the project root, it is unresolvable."
def test_single_dot_import_at_the_root_is_still_inside(infer):
    files = {"helpers.py": WIDGET}
    definition = infer("from . import helpers\nhelpers.Wid|get\n", files=files).only
    assert definition["module_path"] == "helpers.py"


# Spec: "infer now follows imports to resolve types across files."
def test_infer_follows_a_chain_of_imports(infer):
    files = {"middle.py": "from base import Widget\n", "base.py": WIDGET}
    definition = infer("from middle import Widget\nw = Widget()\n|w\n", files=files).only
    assert definition["module_path"] == "base.py"
    assert definition["type"] == "instance"


# Spec: "`infer` now follows imports to resolve types across files."
def test_infer_a_call_returning_an_imported_class(infer):
    files = {
        "factory.py": "from base import Widget\n\n\ndef build():\n    return Widget()\n",
        "base.py": WIDGET,
    }
    definition = infer("import factory\nw = factory.build()\n|w\n", files=files).only
    assert (definition["name"], definition["module_path"]) == ("Widget", "base.py")
