"""`from X import *`: which names the importing module can then see."""

ALL_MODULE = (
    '__all__ = ["alpha", "_kept"]\n'
    "alpha = 1\n"
    "beta = 2\n"
    "_kept = 3\n"
    "_hidden = 4\n"
)

PLAIN_MODULE = "alpha = 1\nbeta = 2\n_hidden = 3\n"


# Spec: "Makes all public names from `foo` visible in the importing module."
def test_star_import_exposes_module_names(complete):
    names = complete("from plain import *\n|\n", files={"plain.py": PLAIN_MODULE}).names
    assert {"alpha", "beta"} <= set(names)


# Spec: "The module defines `__all__`: use exactly those names."
def test_star_import_honours_dunder_all(complete):
    names = set(complete("from exports import *\n|\n", files={"exports.py": ALL_MODULE}).names)
    assert {"alpha", "_kept"} <= names
    assert "beta" not in names
    assert "_hidden" not in names


# Spec: "Otherwise: all names that do not start with `_`."
def test_star_import_without_dunder_all_hides_underscores(complete):
    names = set(complete("from plain import *\n|\n", files={"plain.py": PLAIN_MODULE}).names)
    assert "_hidden" not in names


# Spec: star imports resolve through packages too.
def test_star_import_of_a_package_submodule(complete):
    files = {"pkg/__init__.py": "", "pkg/tools.py": PLAIN_MODULE}
    names = set(complete("from pkg.tools import *\n|\n", files=files).names)
    assert {"alpha", "beta"} <= names


# Spec: relative star import.
def test_relative_star_import(complete):
    files = {"pkg/__init__.py": "", "pkg/tools.py": PLAIN_MODULE}
    result = complete("from .tools import *\n|\n", name="pkg/app.py", files=files, project=".")
    assert {"alpha", "beta"} <= set(result.names)


# Spec: "Import of nonexistent module: not an error -- return empty results."
def test_star_import_of_a_missing_module_is_quiet(complete):
    result = complete("from nowhere_at_all import *\nalph|\n")
    assert result.returncode == 0
    assert result.completions == []


# Spec: a star-imported name can be navigated to, not only completed.
def test_infer_a_star_imported_name(infer):
    definition = infer("from plain import *\n|alpha\n", files={"plain.py": PLAIN_MODULE}).only
    assert definition["type"] == "instance"
