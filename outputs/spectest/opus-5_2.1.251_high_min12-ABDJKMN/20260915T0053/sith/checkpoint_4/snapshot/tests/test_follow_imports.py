"""Spec section: `goto` Changes (`--follow-imports`)."""
from conftest import CURSOR, defs_in, one

C = CURSOR

HELPER = 'def greet(name):\n    """Say hi."""\n    return "hi " + name\n'


# --- Phrase: "Without `--follow-imports` (default), `goto` on an imported name
#              returns the `import` statement itself"
#     Context: cursor on the bound name at a use site.
def test_goto_default_returns_import_statement(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "from helper import greet\n" + C + "greet('x')\n",
    }
    got = one(defs_in(tmp_path, files, "goto"))
    assert got["module_path"] == "main.py"
    assert got["line"] == 1
    assert got["description"] == "from helper import greet"


# --- Phrase: "Without `--follow-imports` (default), `goto` on an imported name
#              returns the `import` statement itself"
#     Context: cursor on the name inside the import statement.
def test_goto_default_on_import_line(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "from helper import gr" + C + "eet\n",
    }
    got = one(defs_in(tmp_path, files, "goto"))
    assert (got["module_path"], got["line"], got["column"]) == ("main.py", 1, 19)


# --- Phrase: "With `--follow-imports`, `goto` follows the import chain and
#              returns the actual definition in the source module"
#     Context: a function imported from a sibling module.
def test_follow_imports_reaches_source_module(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "from helper import greet\n" + C + "greet('x')\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "helper.py"
    assert got["line"] == 1
    assert got["type"] == "function"
    assert got["full_name"] == "helper.greet"


# --- Phrase: "returns the actual definition in the source module"
#     Context: an imported class.
def test_follow_imports_class(tmp_path):
    files = {
        "models.py": "class Widget:\n    pass\n",
        "main.py": "from models import Widget\nW" + C + "idget()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"], got["type"]) == \
        ("models.py", 1, "class")


# --- Phrase: "returns the actual definition in the source module"
#     Context: an imported module-level assignment.
def test_follow_imports_assignment(tmp_path):
    files = {
        "conf.py": "SETTING = 5\n",
        "main.py": "from conf import SETTING\n" + C + "SETTING\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"], got["type"]) == \
        ("conf.py", 1, "statement")


# --- Phrase: "`--follow-imports` follows the import chain to the final definition."
#     Context: a re-export chain main -> mid -> base.
def test_follow_imports_multi_hop_chain(tmp_path):
    files = {
        "base.py": "def target():\n    pass\n",
        "mid.py": "from base import target\n",
        "main.py": "from mid import target\n" + C + "target()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "base.py"
    assert got["full_name"] == "base.target"


# --- Phrase: "`--follow-imports` follows the import chain to the final definition."
#     Context: the chain passes through a package `__init__.py` re-export.
def test_follow_imports_through_package_init(tmp_path):
    files = {
        "pkg/__init__.py": "from pkg.core import work\n",
        "pkg/core.py": "def work():\n    pass\n",
        "main.py": "from pkg import work\n" + C + "work()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "pkg/core.py"


# --- Phrase: "`--follow-imports` follows the import chain to the final definition."
#     Context: the chain passes through a star import.
def test_follow_imports_through_star_import(tmp_path):
    files = {
        "base.py": "def target():\n    pass\n",
        "mid.py": "from base import *\n",
        "main.py": "from mid import target\n" + C + "target()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "base.py"


# --- Phrase: "With `--follow-imports`, `goto` follows the import chain"
#     Context: a whole-module import lands on the module file.
def test_follow_imports_on_module_name(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "import helper\n" + C + "helper.greet\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "helper.py"
    assert got["type"] == "module"


# --- Phrase: "If the import chain leads to a module that cannot be found
#              (e.g., third-party or stdlib), return the import statement as a fallback."
#     Context: stdlib import under --follow-imports.
def test_follow_imports_stdlib_falls_back(tmp_path):
    files = {"main.py": "from os import getcwd\n" + C + "getcwd()\n"}
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "main.py"
    assert got["description"] == "from os import getcwd"


# --- Phrase: "... (e.g., third-party or stdlib), return the import statement as a fallback."
#     Context: an entirely missing module under --follow-imports.
def test_follow_imports_missing_module_falls_back(tmp_path):
    files = {"main.py": "from nope_zzz_pkg import thing\n" + C + "thing\n"}
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"]) == ("main.py", 1)


# --- Phrase: Clarification "With `--follow-imports`, if the terminal target cannot
#              be resolved, return the import site in the current file as the fallback"
#     Context: the module resolves but the imported name is not defined in it.
def test_follow_imports_missing_name_falls_back(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "from helper import absent\n" + C + "absent\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"]) == ("main.py", 1)


# --- Phrase: "`goto` on an imported name"
#     Context: --follow-imports leaves ordinary local names untouched.
def test_follow_imports_ignores_local_names(tmp_path):
    files = {"main.py": "def local():\n    pass\n\n\n" + C + "local()\n"}
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"]) == ("main.py", 1)


# --- Phrase: "With `--follow-imports`, `goto` follows the import chain and returns
#              the actual definition in the source module"
#     Context: an aliased import.
def test_follow_imports_alias(tmp_path):
    files = {
        "helper.py": HELPER,
        "main.py": "from helper import greet as hello\n" + C + "hello('x')\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert (got["module_path"], got["line"], got["name"]) == \
        ("helper.py", 1, "greet")


# --- Phrase: "With `--follow-imports`, `goto` follows the import chain"
#     Context: attribute access through an imported module re-export.
def test_follow_imports_attribute_of_reexporting_module(tmp_path):
    files = {
        "base.py": "def target():\n    pass\n",
        "mid.py": "from base import target\n",
        "main.py": "import mid\nmid.tar" + C + "get()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True))
    assert got["module_path"] == "base.py"


# --- Phrase: "Without `--follow-imports` (default) ... returns the `import`
#              statement itself"
#     Context: the same attribute without the flag stops at mid.py's import line.
def test_attribute_of_reexporting_module_without_flag(tmp_path):
    files = {
        "base.py": "def target():\n    pass\n",
        "mid.py": "from base import target\n",
        "main.py": "import mid\nmid.tar" + C + "get()\n",
    }
    got = one(defs_in(tmp_path, files, "goto"))
    assert (got["module_path"], got["line"]) == ("mid.py", 1)


# --- Phrase: "`--follow-imports` follows the import chain to the final definition."
#     Context: a relative re-export chain inside a package.
def test_follow_imports_relative_chain(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/base.py": "def target():\n    pass\n",
        "pkg/mid.py": "from .base import target\n",
        "pkg/app.py": "from .mid import target\n" + C + "target()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", follow=True, project=tmp_path))
    assert got["module_path"] == "pkg/base.py"
