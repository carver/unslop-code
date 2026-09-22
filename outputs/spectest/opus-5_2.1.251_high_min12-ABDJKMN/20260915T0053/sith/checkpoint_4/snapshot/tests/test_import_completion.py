"""Spec section: `complete` Changes - Import Context Completion."""
from conftest import CURSOR, comps_in, entry, has, names

C = CURSOR


# --- Phrase: "`import ...` suggests top-level module/package names."
#     Context: a project module at the root.
def test_import_suggests_project_module(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n",
        "main.py": "import hel" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "helper") == {
        "name": "helper", "complete": "per", "type": "module",
        "description": "module helper",
    }


# --- Phrase: "`import ...` suggests top-level module/package names."
#     Context: a package directory is suggested too.
def test_import_suggests_package(tmp_path):
    files = {
        "mypkg/__init__.py": "",
        "main.py": "import myp" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "mypkg")["type"] == "module"


# --- Phrase: "`import |` suggests top-level module/package names."
#     Context: empty prefix right after `import `.
def test_import_empty_prefix_lists_modules(tmp_path):
    files = {
        "alpha.py": "",
        "beta.py": "",
        "main.py": "import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "alpha")
    assert has(data, "beta")


# --- Phrase: "`import |` suggests top-level module/package names."
#     Context: only modules - no keywords or builtins leak in.
def test_import_context_excludes_keywords_and_builtins(tmp_path):
    files = {"alpha.py": "", "main.py": "import " + C + "\n"}
    data = comps_in(tmp_path, files)
    assert not has(data, "len")
    assert not has(data, "lambda")
    assert not has(data, "if")


# --- Phrase: "`import ...` suggests top-level module/package names."
#     Context: stdlib modules are reachable, so they are offered too.
def test_import_suggests_stdlib(tmp_path):
    files = {"main.py": "import jso" + C + "\n"}
    data = comps_in(tmp_path, files)
    assert has(data, "json")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: functions and classes of a project module.
def test_from_import_suggests_module_names(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n\n\nclass Greeter:\n    pass\n",
        "main.py": "from helper import g" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "greet")["type"] == "function"
    assert entry(data, "Greeter")["type"] == "class"  # matching is case-folded
    assert not has(data, "object")  # only names inside the module


# --- Phrase: "`from X import |` suggests names inside module `X`."
#     Context: empty prefix lists every exported name.
def test_from_import_empty_prefix(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n\n\nclass Greeter:\n    pass\n",
        "main.py": "from helper import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "greet")
    assert entry(data, "Greeter")["type"] == "class"


# --- Phrase: "`from X.Y import ...` suggests names inside submodule `X.Y`."
#     Context: dotted module path.
def test_from_submodule_import(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": "def inner():\n    pass\n",
        "main.py": "from pkg.mod import i" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "inner")["type"] == "function"


# --- Phrase: "`from X.Y import |` suggests names inside submodule `X.Y`."
#     Context: empty prefix after a dotted module path.
def test_from_submodule_import_empty_prefix(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": "VALUE = 1\n\n\ndef inner():\n    pass\n",
        "main.py": "from pkg.mod import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "VALUE")
    assert has(data, "inner")


# --- Phrase: Clarification "In `from X import ...` completion, exported names come
#              from `__all__` when it exists"
#     Context: `__all__` restricts the offered names.
def test_from_import_honours_dunder_all(tmp_path):
    files = {
        "helper.py": "__all__ = ['alpha']\n\n\ndef alpha():\n    pass\n\n\n"
                     "def beta():\n    pass\n",
        "main.py": "from helper import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "alpha")
    assert not has(data, "beta")


# --- Phrase: Clarification "... otherwise use names that do not start with `_`."
#     Context: no `__all__` in the source module.
def test_from_import_hides_underscore_without_all(tmp_path):
    files = {
        "helper.py": "def alpha():\n    pass\n\n\ndef _hidden():\n    pass\n",
        "main.py": "from helper import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "alpha")
    assert not has(data, "_hidden")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: a package offers its submodules as importable names.
def test_from_package_import_offers_submodules(tmp_path):
    files = {
        "pkg/__init__.py": "NAME = 'pkg'\n",
        "pkg/mod.py": "",
        "main.py": "from pkg import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "mod")
    assert has(data, "NAME")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: an unresolvable module offers nothing.
def test_from_missing_module_import_is_empty(tmp_path):
    files = {"main.py": "from nope_zzz_pkg import " + C + "\n"}
    assert comps_in(tmp_path, files)["completions"] == []


# --- Phrase: "Import completions use the same ordering rules
#              (public -> private -> dunder) ... as name completions."
#     Context: `__all__` mixing public, private and dunder names.
def test_import_completion_ordering(tmp_path):
    files = {
        "helper.py": "__all__ = ['__magic__', '_priv', 'zeta', 'alpha']\n"
                     "alpha = 1\nzeta = 2\n_priv = 3\n__magic__ = 4\n",
        "main.py": "from helper import " + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert names(data) == ["alpha", "zeta", "_priv", "__magic__"]


# --- Phrase: "Import completions use ... prefix matching as name completions."
#     Context: the `complete` field is the remainder after the typed prefix.
def test_import_completion_prefix_remainder(tmp_path):
    files = {
        "helper.py": "def greeting():\n    pass\n",
        "main.py": "from helper import gre" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "greeting")["complete"] == "eting"


# --- Phrase: "Import completions use ... prefix matching as name completions."
#     Context: `--fuzzy` applies in import context too.
def test_import_completion_fuzzy(tmp_path):
    files = {
        "helper.py": "def greeting():\n    pass\n",
        "main.py": "from helper import gtn" + C + "\n",
    }
    data = comps_in(tmp_path, files, fuzzy=True)
    assert has(data, "greeting")


# --- Phrase: "`import ...` suggests top-level module/package names."
#     Context: a dotted `import X.` offers submodules of X.
def test_import_dotted_offers_submodules(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/mod.py": "",
        "main.py": "import pkg." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "mod")


# --- Phrase: "`from X import ...`"
#     Context: the module name position after `from` completes modules.
def test_from_module_position_completes_modules(tmp_path):
    files = {
        "helper.py": "",
        "main.py": "from hel" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "helper")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: a second name after a comma is still an import completion.
def test_from_import_after_comma(tmp_path):
    files = {
        "helper.py": "def alpha():\n    pass\n\n\ndef beta():\n    pass\n",
        "main.py": "from helper import alpha, b" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "beta")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: relative module references resolve from the current package.
def test_from_relative_import_completion(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/helper.py": "def alpha():\n    pass\n",
        "pkg/app.py": "from .helper import " + C + "\n",
    }
    data = comps_in(tmp_path, files, project=tmp_path)
    assert has(data, "alpha")


# --- Phrase: "`from X import ...` suggests names inside module `X`."
#     Context: stdlib module members are offered.
def test_from_stdlib_import_completion(tmp_path):
    files = {"main.py": "from json import du" + C + "\n"}
    data = comps_in(tmp_path, files)
    assert has(data, "dumps")


# --- Phrase: "`from X import |` suggests names inside module `X`."
#     Context: a parenthesised import list continued on the next line.
def test_from_import_parenthesised_continuation(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n",
        "main.py": "from helper import (\n    gr" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "greet")


# --- Phrase: "`from X import |` suggests names inside module `X`."
#     Context: a backslash-continued import statement.
def test_from_import_backslash_continuation(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n",
        "main.py": "from helper import \\\n    gr" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "greet")


# --- Phrase: "`import ...` suggests top-level module/package names."
#     Context: an aliased import offers nothing after `as`.
def test_import_after_as_offers_nothing(tmp_path):
    files = {"helper.py": "", "main.py": "import helper as h" + C + "\n"}
    assert comps_in(tmp_path, files)["completions"] == []


# --- Phrase: "`from X import ...`"
#     Context: `from X import *` is not a name-completion position.
def test_from_import_star_offers_nothing(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n",
        "main.py": "from helper import *" + C + "\n",
    }
    assert comps_in(tmp_path, files)["completions"] == []
