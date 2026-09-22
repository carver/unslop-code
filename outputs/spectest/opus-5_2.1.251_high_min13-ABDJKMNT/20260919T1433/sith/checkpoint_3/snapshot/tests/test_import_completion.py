"""Spec: completion inside import statements, and across file boundaries."""

HELPER = "alpha = 1\n\n\nclass Thing:\n    def method(self):\n        pass\n"
PACKAGE = {"pkg/__init__.py": "in_init = 1\n", "pkg/inner.py": HELPER}


# Spec: "`import |` suggests top-level module/package names."
def test_import_suggests_project_modules(complete):
    names = complete("import $\n", extra={"helper.py": HELPER}).names
    assert "helper" in names


def test_import_suggests_packages(complete):
    names = complete("import $\n", extra=PACKAGE, project=".").names
    assert "pkg" in names


def test_import_suggests_standard_library_modules(complete):
    assert "os" in complete("import $\n").names


def test_import_suggestions_are_modules(complete):
    item = complete("import $\n", extra={"helper.py": HELPER}).by_name("helper")
    assert (item["type"], item["description"]) == ("module", "module helper")


# Spec: "Import completions use the same ordering rules (public -> private ->
# dunder) and prefix matching as name completions."
def test_import_module_names_are_prefix_matched(complete):
    extra = {"helper.py": HELPER, "other.py": ""}
    result = complete("import helpe$\n", extra=extra)
    assert "other" not in result.names
    assert result.by_name("helper")["complete"] == "r"


# Spec: "`from X import |` suggests names inside module `X`."
def test_from_import_suggests_names_in_the_module(complete):
    names = complete("from helper import $\n", extra={"helper.py": HELPER}).names
    assert {"alpha", "Thing"} <= set(names)


def test_from_import_keeps_the_kind_of_each_name(complete):
    result = complete("from helper import $\n", extra={"helper.py": HELPER})
    assert result.by_name("Thing")["type"] == "class"


# Spec: "`from X.Y import |` suggests names inside submodule `X.Y`."
def test_from_import_of_a_submodule(complete):
    names = complete("from pkg.inner import $\n", extra=PACKAGE, project=".").names
    assert {"alpha", "Thing"} <= set(names)
    assert "in_init" not in names


def test_from_import_of_a_package_suggests_its_submodules(complete):
    names = complete("from pkg import $\n", extra=PACKAGE, project=".").names
    assert {"in_init", "inner"} <= set(names)


# T36: the module written after `from` is completed like an `import` path.
def test_from_suggests_module_names(complete):
    assert "helper" in complete("from $\n", extra={"helper.py": HELPER}).names


# Spec: "exported names come from `__all__` when it exists; otherwise use
# names that do not start with `_`."
def test_from_import_uses_dunder_all(complete):
    helper = "__all__ = ['alpha', '_kept']\nalpha = 1\n_kept = 2\ngamma = 3\n"
    names = complete("from helper import $\n", extra={"helper.py": helper}).names
    assert names == ["alpha", "_kept"]


def test_from_import_hides_private_names_without_dunder_all(complete):
    helper = "alpha = 1\n_hidden = 2\n"
    names = complete("from helper import $\n", extra={"helper.py": helper}).names
    assert names == ["alpha"]


# Spec: "Import completions use the same ordering rules (public -> private ->
# dunder)".
def test_import_names_are_ordered_by_group(complete):
    helper = "__all__ = ['zeta', '_priv', '__dunder__', 'alpha']\n"
    names = complete("from helper import $\n", extra={"helper.py": helper}).names
    assert names == ["alpha", "zeta", "_priv", "__dunder__"]


def test_from_import_names_are_prefix_matched(complete):
    result = complete("from helper import al$\n", extra={"helper.py": HELPER})
    assert result.names == ["alpha"]
    assert result.by_name("alpha")["complete"] == "pha"


def test_from_import_completes_after_a_comma(complete):
    names = complete("from helper import alpha, $\n", extra={"helper.py": HELPER}).names
    assert "Thing" in names


# Spec: relative imports are written the same way in an import statement.
def test_from_relative_import_suggests_sibling_names(complete):
    extra = {"pkg/__init__.py": "", "pkg/sibling.py": HELPER}
    result = complete("from .sibling import $\n", name="pkg/main.py", extra=extra, project=".")
    assert "alpha" in result.names


def test_relative_from_suggests_sibling_modules(complete):
    extra = {"pkg/__init__.py": "", "pkg/sibling.py": HELPER}
    result = complete("from .$\n", name="pkg/main.py", extra=extra, project=".")
    assert "sibling" in result.names


# Spec: "If a module cannot be found ... completions return nothing".
def test_from_import_of_an_unknown_module_suggests_nothing(complete):
    result = complete("from no_such_module import $\n")
    assert result.code == 0
    assert result.names == []


# Spec: "Cross-File Attribute Completion - attribute completion now works for
# imported names."
def test_attributes_of_an_imported_class(complete):
    names = complete(
        "from helper import Thing\nThing.$\n", extra={"helper.py": HELPER}
    ).names
    assert "method" in names


def test_attributes_of_an_instance_of_an_imported_class(complete):
    names = complete(
        "from helper import Thing\nvalue = Thing()\nvalue.$\n",
        extra={"helper.py": HELPER},
    ).names
    assert "method" in names


def test_attributes_of_an_imported_package(complete):
    names = complete("import pkg\npkg.$\n", extra=PACKAGE, project=".").names
    assert {"in_init", "inner"} <= set(names)


def test_attributes_of_an_imported_submodule(complete):
    names = complete(
        "import pkg.inner\npkg.inner.$\n", extra=PACKAGE, project="."
    ).names
    assert {"alpha", "Thing"} <= set(names)


# T36: a dotted module path is completed a segment at a time.
def test_import_completes_submodules_after_a_dot(complete):
    names = complete("import pkg.$\n", extra=PACKAGE, project=".").names
    assert "inner" in names


def test_import_completes_submodules_of_a_standard_library_package(complete):
    assert "decoder" in complete("import json.$\n").names


def test_import_completes_a_module_a_package_re_exports(complete):
    assert "path" in complete("import os.$\n").names


# Spec: "`from X import |` suggests names inside module `X`" - `X` may be a
# module of the standard library.
def test_from_import_of_a_standard_library_module(complete):
    assert "getcwd" in complete("from os import $\n").names


def test_from_import_of_a_standard_library_submodule(complete):
    assert "join" in complete("from os.path import $\n").names
