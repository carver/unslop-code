"""Spec: resolving import statements to their source files in the project."""

THING = "class Thing:\n    pass\n"


# Spec: "Project root - scan for `.py` files"
def test_root_level_module_resolves(infer):
    result = infer("import helper\nhelper.Thin$g\n", extra={"helper.py": THING})
    assert (result.only["module_path"], result.only["line"]) == ("helper.py", 1)


# Spec: "and packages (directories containing `__init__.py`)."
def test_package_resolves_through_its_init(infer):
    result = infer(
        "import pkg\npk$g\n",
        extra={"pkg/__init__.py": "value = 1\n"},
        project=".",
    )
    assert result.only["module_path"] == "pkg/__init__.py"
    assert result.only["full_name"] == "pkg"


def test_submodule_of_a_package_resolves(infer):
    result = infer(
        "from pkg.inner import Thing\nThin$g\n",
        extra={"pkg/__init__.py": "", "pkg/inner.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "pkg/inner.py"


# Spec: a dotted `import` binds the root package, whose attributes reach the
# submodule it names.
def test_dotted_import_reaches_the_submodule(infer):
    result = infer(
        "import pkg.inner\npkg.inner.Thin$g\n",
        extra={"pkg/__init__.py": "", "pkg/inner.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "pkg/inner.py"


# Spec: "The same import rules apply to regular packages and namespace
# packages." - a directory with no `__init__.py`.
def test_namespace_package_resolves(infer):
    result = infer(
        "from space.inner import Thing\nThin$g\n",
        extra={"space/inner.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "space/inner.py"


def test_namespace_package_itself_is_a_module(infer):
    result = infer("import space\nspac$e\n", extra={"space/inner.py": THING}, project=".")
    assert result.only["type"] == "module"
    assert result.only["full_name"] == "space"


# Spec: "Standard library - recognize stdlib modules available in the target
# runtime."
def test_standard_library_module_resolves(infer):
    assert infer("import os\nos.getcw$d\n").only["name"] == "getcwd"


# Spec: search order - "1. Project root ... 2. Standard library".
def test_project_module_shadows_the_standard_library(infer):
    result = infer("import json\njson.Thin$g\n", extra={"json.py": THING})
    assert result.only["module_path"] == "json.py"


# Spec: "If a module cannot be found, treat it as unresolvable - `infer` and
# `goto` return empty results".
def test_unresolvable_module_infers_nothing(infer):
    assert infer("import no_such_module\nno_such_modul$e\n").definitions == []


def test_unresolvable_module_attribute_gotos_nothing(goto):
    assert goto("import no_such_module\nno_such_module.thin$g\n").definitions == []


# Spec: "completions return nothing for that module's attributes."
def test_unresolvable_module_completes_nothing(complete):
    assert complete("import no_such_module\nno_such_module.$\n").names == []


# Spec: "Import of nonexistent module: not an error".
def test_unresolvable_module_is_not_an_error(complete):
    assert complete("import no_such_module\nno_such_module.$\n").code == 0


# Spec: relative imports resolve against the importing module's package.
def test_relative_import_of_a_sibling_module(infer):
    result = infer(
        "from .sibling import Thing\nThin$g\n",
        name="pkg/main.py",
        extra={"pkg/__init__.py": "", "pkg/sibling.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "pkg/sibling.py"


def test_relative_import_of_a_sibling_by_name(infer):
    result = infer(
        "from . import sibling\nsibling.Thin$g\n",
        name="pkg/main.py",
        extra={"pkg/__init__.py": "", "pkg/sibling.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "pkg/sibling.py"


def test_relative_import_reaches_the_parent_package(infer):
    result = infer(
        "from ..shared import Thing\nThin$g\n",
        name="pkg/inner/main.py",
        extra={"pkg/__init__.py": "", "pkg/inner/__init__.py": "", "pkg/shared.py": THING},
        project=".",
    )
    assert result.only["module_path"] == "pkg/shared.py"


# Spec: "If the relative import goes above the project root, it is
# unresolvable."
def test_relative_import_above_the_root_is_unresolvable(infer):
    result = infer(
        "from ..outside import Thing\nThin$g\n",
        name="pkg/main.py",
        extra={"pkg/__init__.py": "", "outside.py": THING},
        project="pkg",
    )
    assert result.definitions == []


def test_relative_import_far_above_the_root_is_unresolvable(infer):
    result = infer(
        "from ...far import Thing\nThin$g\n",
        name="pkg/main.py",
        extra={"pkg/__init__.py": "", "far.py": THING},
        project=".",
    )
    assert result.definitions == []


# Spec: "Makes all public names from `foo` visible in the importing module."
def test_star_import_exposes_project_names(complete):
    helper = "alpha = 1\ndef beta():\n    pass\n"
    names = complete("from helper import *\n$\n", extra={"helper.py": helper}).names
    assert {"alpha", "beta"} <= set(names)


# Spec: "Otherwise: all names that do not start with `_`."
def test_star_import_hides_underscored_names(complete):
    helper = "alpha = 1\n_hidden = 2\n"
    names = complete("from helper import *\n$\n", extra={"helper.py": helper}).names
    assert "_hidden" not in names


# Spec: "The module defines `__all__`: use exactly those names."
def test_star_import_honours_dunder_all(complete):
    helper = "__all__ = ['alpha', '_kept']\nalpha = 1\n_kept = 2\ngamma = 3\n"
    names = complete("from helper import *\n$\n", extra={"helper.py": helper}).names
    assert "alpha" in names and "_kept" in names
    assert "gamma" not in names


# Spec: "Circular imports: do not infinite-loop."
def test_circular_imports_terminate(infer):
    extra = {
        "left.py": "from right import Right\n\n\nclass Left:\n    pass\n",
        "right.py": "from left import Left\n\n\nclass Right:\n    pass\n",
    }
    result = infer("from left import Left\nLef$t\n", extra=extra)
    assert result.code == 0
    assert result.only["module_path"] == "left.py"


def test_circular_import_completion_terminates(complete):
    extra = {
        "left.py": "from right import *\nalpha = 1\n",
        "right.py": "from left import *\nbeta = 2\n",
    }
    result = complete("import left\nleft.$\n", extra=extra)
    assert result.code == 0
    assert "alpha" in result.names


# Spec: "Syntax errors in imported files: parse as much as possible (same
# tolerance as the main file)."
def test_syntax_error_in_an_imported_file_is_tolerated(infer):
    helper = "def broken(:\n    pass\nclass Thing:\n    pass\n"
    result = infer("from helper import Thing\nThin$g\n", extra={"helper.py": helper})
    assert (result.only["module_path"], result.only["line"]) == ("helper.py", 3)


# Spec: "`infer` now follows imports to resolve types across files."
def test_infer_follows_an_imported_factory(infer):
    helper = "class Thing:\n    pass\n\n\ndef build():\n    return Thing()\n"
    result = infer(
        "from helper import build\nvalue = build()\nvalu$e\n",
        extra={"helper.py": helper},
    )
    assert (result.only["type"], result.only["full_name"]) == ("instance", "helper.Thing")


def test_infer_follows_an_imported_annotation(infer):
    helper = "class Thing:\n    def method(self):\n        return 1\n"
    result = infer(
        "from helper import Thing\n\n\ndef use(item: Thing):\n    return item.metho$d()\n",
        extra={"helper.py": helper},
    )
    assert (result.only["module_path"], result.only["name"]) == ("helper.py", "method")


def test_infer_follows_a_re_exported_name(infer):
    extra = {"base.py": THING, "middle.py": "from base import Thing\n"}
    result = infer("from middle import Thing\nThin$g\n", extra=extra)
    assert result.only["module_path"] == "base.py"
