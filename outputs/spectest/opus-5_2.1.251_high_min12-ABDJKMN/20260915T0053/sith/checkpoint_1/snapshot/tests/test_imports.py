"""Spec section: import handling ("`import os` makes `os` visible as a module", star imports)."""
from conftest import CURSOR, complete_at, entry, has

C = CURSOR


# --- Phrase: "`import os` makes `os` visible as a module."
#     Context: plain import at module level.
def test_import_makes_module_visible(tmp_path):
    data = complete_at(tmp_path, "import os\no" + C + "\n")
    assert entry(data, "os") == {
        "name": "os", "complete": "s", "type": "module", "description": "module os",
    }


# --- Phrase: "For imports: `module name`."
#     Context: description template uses the bound name.
def test_dotted_import_binds_root_package(tmp_path):
    data = complete_at(tmp_path, "import os.path\n" + C + "\n")
    assert entry(data, "os")["type"] == "module"
    assert entry(data, "os")["description"] == "module os"
    assert not has(data, "os.path")


# --- Phrase: "For imports: `module name`."
#     Context: aliased import binds the alias.
def test_aliased_import(tmp_path):
    data = complete_at(tmp_path, "import os.path as osp\n" + C + "\n")
    assert entry(data, "osp")["type"] == "module"
    assert entry(data, "osp")["description"] == "module osp"


# --- Phrase: "For imported names (from import statements), the `type` reflects the imported
#              object's actual kind if inferable (e.g., `function`, `class`, `module`)."
#     Context: from-import of a function, a class and a module.
def test_from_import_types(tmp_path):
    code = (
        "from os import getcwd\n"
        "from os import path\n"
        "from decimal import Decimal\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert entry(data, "getcwd")["type"] == "function"
    assert entry(data, "path")["type"] == "module"
    assert entry(data, "Decimal")["type"] == "class"


# --- Phrase: "If not inferable, use `statement`."
#     Context: an import of a module that does not exist.
def test_uninferable_import_is_statement(tmp_path):
    code = "from totally_missing_pkg_xyz import thing\n" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "thing")["type"] == "statement"


# --- Phrase: "For imports: `module name`" + inferred kinds (T6)
#     Context: descriptions follow the resolved kind.
def test_from_import_descriptions(tmp_path):
    code = (
        "from os import getcwd\n"
        "from os import path\n"
        "from decimal import Decimal\n"
        "from totally_missing_pkg_xyz import thing\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert entry(data, "getcwd")["description"] == "def getcwd(...)"
    assert entry(data, "path")["description"] == "module path"
    assert entry(data, "Decimal")["description"] == "class Decimal"
    assert entry(data, "thing")["description"] == "module thing"


# --- Phrase: "`from os import *` makes all public names from `os` visible."
#     Context: star import from an installed package.
def test_star_import_from_installed_package(tmp_path):
    data = complete_at(tmp_path, "from os import *\n" + C + "\n")
    assert has(data, "getcwd")
    assert has(data, "sep")


# --- Phrase: "makes all public names from `os` visible"
#     Context: private names are not brought in by the star import.
def test_star_import_skips_private(tmp_path):
    data = complete_at(tmp_path, "from string import *\n" + C + "\n")
    assert has(data, "capwords")
    assert not has(data, "_string")


# --- Phrase: "Star imports resolve both installed packages and local project modules
#              (files in the same directory)."
#     Context: a sibling .py file.
def test_star_import_from_local_module(tmp_path):
    local = "LOCAL_CONST = 1\n\n\ndef local_func():\n    pass\n\n\nclass LocalClass:\n    pass\n\n_hidden = 2\n"
    data = complete_at(
        tmp_path,
        "from helper import *\n" + C + "\n",
        extra={"helper.py": local},
    )
    assert entry(data, "LOCAL_CONST")["description"] == "instance of int"
    assert entry(data, "local_func")["type"] == "function"
    assert entry(data, "LocalClass")["type"] == "class"
    assert not has(data, "_hidden")


# --- Phrase: "local project modules (files in the same directory)"
#     Context: importing a local module and completing its attributes.
def test_local_module_attribute_completion(tmp_path):
    local = "def local_func():\n    pass\n\n\nclass LocalClass:\n    pass\n"
    data = complete_at(
        tmp_path,
        "import helper\nhelper." + C + "\n",
        extra={"helper.py": local},
    )
    assert has(data, "local_func")
    assert has(data, "LocalClass")


# --- Phrase: "from ... import" of a local module member.
#     Context: the imported object's kind comes from the local file.
def test_from_local_module_import_name(tmp_path):
    local = "def local_func():\n    pass\n"
    data = complete_at(
        tmp_path,
        "from helper import local_func\n" + C + "\n",
        extra={"helper.py": local},
    )
    assert entry(data, "local_func")["type"] == "function"


# --- Phrase: "A name is visible only if it is defined before the cursor position"
#     Context: star-imported names obey the positional rule too.
def test_star_import_after_cursor_not_visible(tmp_path):
    code = C + "\nfrom os import *\n"
    data = complete_at(tmp_path, code)
    assert not has(data, "getcwd")


# --- Phrase: "`import os` makes `os` visible as a module."
#     Context: imports inside a function are local names.
def test_import_inside_function(tmp_path):
    code = (
        "def f():\n"
        "    import os\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert entry(data, "os")["type"] == "module"
