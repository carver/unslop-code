"""Spec section: Import Resolution (absolute, relative, star)."""
from conftest import CURSOR, comps_in, defs_in, entry, has, one

C = CURSOR


# --- Phrase: "Project root - scan for `.py` files ..."
#     Context: a plain module at the project root resolves.
def test_absolute_import_of_root_module(tmp_path):
    files = {
        "lib.py": "def helper():\n    pass\n",
        "main.py": "import lib\n" + C + "lib\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "module"
    assert got["module_path"] == "lib.py"


# --- Phrase: "... and packages (directories containing `__init__.py`)."
#     Context: `import pkg` resolves to the package's `__init__.py`.
def test_absolute_import_of_package(tmp_path):
    files = {
        "pkg/__init__.py": "VERSION = 1\n",
        "main.py": "import pkg\n" + C + "pkg\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "module"
    assert got["module_path"] == "pkg/__init__.py"
    assert got["full_name"] == "pkg"


# --- Phrase: "scan for `.py` files and packages"
#     Context: a dotted submodule of a package resolves.
def test_absolute_import_of_submodule(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": "def inner():\n    pass\n",
        "main.py": "from pkg.mod import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "pkg/mod.py"
    assert got["full_name"] == "pkg.mod.inner"


# --- Phrase: "Module search order: 1. Project root ... 2. Standard library"
#     Context: a project module shadows a stdlib module of the same name.
def test_project_root_shadows_stdlib(tmp_path):
    files = {
        "string.py": "def project_only():\n    pass\n",
        "main.py": "import string\nstring." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "project_only")
    assert not has(data, "capwords")


# --- Phrase: "Standard library - recognize stdlib modules available in the target runtime."
#     Context: a stdlib module with no project file of that name still resolves.
def test_stdlib_module_resolves(tmp_path):
    files = {"main.py": "import json\njson." + C + "\n"}
    data = comps_in(tmp_path, files)
    assert has(data, "dumps")


# --- Phrase: "If a module cannot be found, treat it as unresolvable -
#              `infer` and `goto` return empty results"
#     Context: `infer` on a name imported from a missing module.
def test_missing_module_infer_is_empty(tmp_path):
    files = {"main.py": "from no_such_module_zzz import thing\n" + C + "thing\n"}
    assert defs_in(tmp_path, files, "infer") == []


# --- Phrase: "... `infer` and `goto` return empty results"
#     Context: `goto` on an attribute of an unresolvable module.
def test_missing_module_goto_attribute_is_empty(tmp_path):
    files = {"main.py": "import no_such_module_zzz\n"
                        + "no_such_module_zzz.thi" + C + "ng\n"}
    assert defs_in(tmp_path, files, "goto") == []


# --- Phrase: "... `infer` and `goto` return empty results" vs. "if the terminal
#              target cannot be resolved, return the import site ... as the fallback"
#     Context: `goto` on the bound name of an unresolvable import keeps the
#              import-site fallback (see AMBIGUITIES T50).
def test_missing_module_goto_bound_name_falls_back(tmp_path):
    files = {"main.py": "from no_such_module_zzz import thing\n"
                        + C + "thing\n"}
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"]) == ("main.py", 1)


# --- Phrase: "completions return nothing for that module's attributes"
#     Context: attribute completion on an unresolvable module.
def test_missing_module_attribute_completion_is_empty(tmp_path):
    files = {"main.py": "import no_such_module_zzz\nno_such_module_zzz."
                        + C + "\n"}
    assert comps_in(tmp_path, files)["completions"] == []


# --- Phrase: "Relative Imports"
#     Context: `from . import sibling` inside a package.
def test_relative_import_sibling_module(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/sibling.py": "def inner():\n    pass\n",
        "pkg/app.py": "from . import sibling\n" + C + "sibling\n",
    }
    got = one(defs_in(tmp_path, files, "infer", project=tmp_path))
    assert got["module_path"] == "pkg/sibling.py"


# --- Phrase: "Relative Imports"
#     Context: `from .sibling import inner` names a member of a sibling module.
def test_relative_import_member(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/sibling.py": "def inner():\n    pass\n",
        "pkg/app.py": "from .sibling import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer", project=tmp_path))
    assert got["full_name"] == "pkg.sibling.inner"


# --- Phrase: "Relative Imports"
#     Context: `..` climbs one package level.
def test_relative_import_parent_package(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/shared.py": "def inner():\n    pass\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/app.py": "from ..shared import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer", project=tmp_path))
    assert got["module_path"] == "pkg/shared.py"


# --- Phrase: "If the relative import goes above the project root, it is unresolvable."
#     Context: two dots from a module directly under the root.
def test_relative_import_above_root_is_unresolvable(tmp_path):
    files = {
        "outside.py": "def inner():\n    pass\n",
        "pkg/__init__.py": "",
        "pkg/app.py": "from ..outside import inner\n" + C + "inner\n",
    }
    assert defs_in(tmp_path, files, "infer", project=tmp_path / "pkg") == []


# --- Phrase: "If the relative import goes above the project root, it is unresolvable."
#     Context: the same import IS resolvable when the root is one level higher.
def test_relative_import_within_root_resolves(tmp_path):
    files = {
        "outside.py": "def inner():\n    pass\n",
        "pkg/__init__.py": "",
        "pkg/app.py": "from ..outside import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer", project=tmp_path))
    assert got["module_path"] == "outside.py"


# --- Phrase: "Star Imports: Makes all public names from `foo` visible in the
#              importing module."
#     Context: names of a project module become visible after `from foo import *`.
def test_star_import_makes_names_visible(tmp_path):
    files = {
        "foo.py": "def alpha():\n    pass\n\n\nclass Beta:\n    pass\n",
        "main.py": "from foo import *\n" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "alpha")["type"] == "function"
    assert entry(data, "Beta")["type"] == "class"


# --- Phrase: "A name is public if: The module defines `__all__`: use exactly those names."
#     Context: `__all__` narrows the visible set.
def test_star_import_uses_dunder_all(tmp_path):
    files = {
        "foo.py": "__all__ = ['alpha', '_secret']\n\n\ndef alpha():\n    pass\n"
                  "\n\ndef beta():\n    pass\n\n\ndef _secret():\n    pass\n",
        "main.py": "from foo import *\n" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "alpha")
    assert has(data, "_secret")
    assert not has(data, "beta")


# --- Phrase: "Otherwise: all names that do not start with `_`."
#     Context: no `__all__`, so underscore names stay hidden.
def test_star_import_without_all_skips_underscore(tmp_path):
    files = {
        "foo.py": "def alpha():\n    pass\n\n\ndef _hidden():\n    pass\n",
        "main.py": "from foo import *\n" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "alpha")
    assert not has(data, "_hidden")


# --- Phrase: "Makes all public names from `foo` visible in the importing module."
#     Context: a star-imported name is resolvable by `infer` / `goto`.
def test_star_imported_name_infers(tmp_path):
    files = {
        "foo.py": "def alpha():\n    pass\n",
        "main.py": "from foo import *\n" + C + "alpha\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "foo.py"


# --- Phrase: "The module defines `__all__`: use exactly those names."
#     Context: a name outside `__all__` is not visible through the star import.
def test_star_import_excluded_name_not_resolvable(tmp_path):
    files = {
        "foo.py": "__all__ = ['alpha']\n\n\ndef alpha():\n    pass\n\n\n"
                  "def beta():\n    pass\n",
        "main.py": "from foo import *\n" + C + "beta\n",
    }
    assert defs_in(tmp_path, files, "infer") == []


# --- Phrase: Clarification "The same import rules apply to regular packages and
#              namespace packages."
#     Context: a directory with no `__init__.py` still works as a package.
def test_namespace_package_import(tmp_path):
    files = {
        "ns/mod.py": "def inner():\n    pass\n",
        "main.py": "from ns.mod import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "ns/mod.py"


# --- Phrase: "The same import rules apply to regular packages and namespace packages."
#     Context: the namespace package itself resolves as a module value.
def test_namespace_package_itself(tmp_path):
    files = {
        "ns/mod.py": "def inner():\n    pass\n",
        "main.py": "import ns\nns." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "mod")


# --- Phrase: "scan for ... packages (directories containing `__init__.py`)"
#     Context: a regular package exposes its submodules as attributes.
def test_package_exposes_submodules(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": "def inner():\n    pass\n",
        "main.py": "import pkg\npkg." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "mod")


# --- Phrase: Clarification "The same import rules apply to regular packages and
#              namespace packages."
#     Context: `infer` on a submodule attribute of a namespace package.
def test_namespace_package_submodule_attribute(tmp_path):
    files = {
        "ns/mod.py": "def inner():\n    pass\n",
        "main.py": "import ns.mod\n" + C + "ns.mod\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "module"
    assert got["module_path"] == "ns"


# --- Phrase: "Standard library - recognize stdlib modules available in the
#              target runtime."
#     Context: the search order names only the project root and the stdlib, so an
#              installed third-party distribution is unresolvable (AMBIGUITIES T49).
def test_third_party_package_is_unresolvable(tmp_path):
    files = {"main.py": "import pyflakes\n" + C + "pyflakes\n"}
    assert defs_in(tmp_path, files, "infer") == []


# --- Phrase: "scan for `.py` files and packages (directories containing `__init__.py`)"
#     Context: a package directory wins over a same-named module file.
def test_package_wins_over_module_file(tmp_path):
    files = {
        "dup/__init__.py": "FROM_PACKAGE = 1\n",
        "dup.py": "FROM_MODULE = 1\n",
        "main.py": "import dup\ndup." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "FROM_PACKAGE")
    assert not has(data, "FROM_MODULE")
