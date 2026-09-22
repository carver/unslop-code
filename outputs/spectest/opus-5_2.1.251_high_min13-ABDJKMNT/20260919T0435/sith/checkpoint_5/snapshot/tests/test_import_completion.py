"""Completion inside `import` and `from ... import ...` statements."""

TOOLS = (
    '__all__ = ["Widget", "build"]\n'
    "class Widget:\n"
    "    pass\n"
    "def build():\n"
    "    return Widget()\n"
    "def hidden_from_all():\n"
    "    pass\n"
)

PLAIN = "class Widget:\n    pass\n\n\ndef build():\n    pass\n\n\n_private = 1\n"

PROJECT = {"helpers.py": PLAIN, "pkg/__init__.py": "ROOT = 1\n", "pkg/tools.py": TOOLS}


# Spec: "`import |` suggests top-level module/package names."
def test_import_suggests_top_level_names(complete):
    names = set(complete("import |\n", files=PROJECT).names)
    assert {"helpers", "pkg"} <= names
    assert "tools" not in names


# Spec: "`import ...` suggests top-level module/package names." (stdlib is on the path too)
def test_import_suggests_stdlib_modules(complete):
    assert "os" in complete("import |\n", files=PROJECT).names


# Spec: "Import completions use the same ... prefix matching as name completions."
def test_import_prefix_matching(complete):
    result = complete("import hel|\n", files=PROJECT)
    assert result.names == ["helpers"]
    assert result.by_name("helpers")["complete"] == "pers"


# Spec: "`import ...` suggests top-level module/package names." -- typed as a module.
def test_import_completion_type_is_module(complete):
    assert complete("import hel|\n", files=PROJECT).by_name("helpers")["type"] == "module"


# Spec: "`from X import |` suggests names inside module `X`."
def test_from_import_suggests_module_members(complete):
    names = set(complete("from helpers import |\n", files=PROJECT).names)
    assert {"Widget", "build"} <= names


# Spec: "In `from X import ...` completion, exported names come from `__all__` when it
#        exists; otherwise use names that do not start with `_`."
def test_from_import_honours_dunder_all(complete):
    names = set(complete("from pkg.tools import |\n", files=PROJECT).names)
    assert {"Widget", "build"} <= names
    assert "hidden_from_all" not in names


def test_from_import_hides_private_names_without_dunder_all(complete):
    assert "_private" not in complete("from helpers import |\n", files=PROJECT).names


# Spec: "`from X.Y import |` suggests names inside submodule `X.Y`."
def test_from_submodule_import_suggests_its_names(complete):
    names = set(complete("from pkg.tools import |\n", files=PROJECT).names)
    assert "Widget" in names
    assert "ROOT" not in names


# Spec: "`from X import ...` suggests names inside module `X`." -- a package exposes both
#        its own names and its submodules.
def test_from_package_import_suggests_submodules(complete):
    names = set(complete("from pkg import |\n", files=PROJECT).names)
    assert {"ROOT", "tools"} <= names


# Spec: "`from X import ...`" against the standard library.
def test_from_stdlib_import_suggests_names(complete):
    assert "getcwd" in complete("from os import |\n", files=PROJECT).names


# Spec: "Import completions use the same ... prefix matching as name completions."
def test_from_import_prefix_matching(complete):
    result = complete("from helpers import Wid|\n", files=PROJECT)
    assert result.names == ["Widget"]
    assert result.by_name("Widget")["complete"] == "get"


# Spec: "Import completions use the same ordering rules (public -> private -> dunder)."
def test_import_completions_are_ordered(complete):
    files = {"alpha.py": "", "_beta.py": "", "zeta.py": ""}
    names = [n for n in complete("import |\n", files=files).names if n in
             {"alpha", "_beta", "zeta"}]
    assert names == ["alpha", "zeta", "_beta"]


# Spec: import completions follow the list through commas.
def test_completion_after_a_comma_in_an_import(complete):
    assert "helpers" in complete("import os, hel|\n", files=PROJECT).names


def test_completion_after_a_comma_in_a_from_import(complete):
    assert "build" in complete("from helpers import Widget, bui|\n", files=PROJECT).names


# Spec: relative import completion resolves against the current package.
def test_from_relative_import_completion(complete):
    result = complete("from .tools import |\n", name="pkg/app.py", files=PROJECT, project=".")
    assert "Widget" in result.names


# Spec: "If a module cannot be found ... completions return nothing for that module's
#        attributes."
def test_from_unknown_module_import_completes_to_nothing(complete):
    assert complete("from nowhere_at_all import |\n", files=PROJECT).completions == []


# Spec: an import statement is not a bare-name context, so ordinary names stay out.
def test_import_context_excludes_local_names(complete):
    source = "alphabet = 1\nfrom helpers import |\n"
    assert "alphabet" not in complete(source, files=PROJECT).names


def test_module_context_excludes_keywords(complete):
    assert "lambda" not in complete("import |\n", files=PROJECT).names
