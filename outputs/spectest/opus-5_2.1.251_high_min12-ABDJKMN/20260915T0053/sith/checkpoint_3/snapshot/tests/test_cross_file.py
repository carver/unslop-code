"""Spec sections: `infer` Changes and Cross-File Attribute Completion."""
from conftest import CURSOR, comps_in, defs_in, entry, has, one

C = CURSOR


# --- Phrase: "`infer` now follows imports to resolve types across files."
#     Context: an imported function.
def test_infer_imported_function(tmp_path):
    files = {
        "helper.py": 'def greet():\n    """Doc."""\n    return 1\n',
        "main.py": "from helper import greet\n" + C + "greet\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "function"
    assert got["module_path"] == "helper.py"
    assert got["docstring"] == "Doc."


# --- Phrase: "`infer` now follows imports to resolve types across files."
#     Context: an instance of an imported class.
def test_infer_instance_of_imported_class(tmp_path):
    files = {
        "models.py": "class Widget:\n    pass\n",
        "main.py": "from models import Widget\nw = Widget()\n" + C + "w\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "instance"
    assert got["full_name"] == "models.Widget"
    assert got["module_path"] == "models.py"


# --- Phrase: "`infer` now follows imports to resolve types across files."
#     Context: the return value of an imported function.
def test_infer_return_of_imported_function(tmp_path):
    files = {
        "helper.py": "class Widget:\n    pass\n\n\ndef make():\n"
                     "    return Widget()\n",
        "main.py": "from helper import make\nw = make()\n" + C + "w\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert (got["type"], got["full_name"]) == ("instance", "helper.Widget")


# --- Phrase: "`infer` now follows imports to resolve types across files."
#     Context: a value imported through two modules.
def test_infer_follows_import_chain(tmp_path):
    files = {
        "base.py": "class Widget:\n    pass\n",
        "mid.py": "from base import Widget\n",
        "main.py": "from mid import Widget\n" + C + "Widget\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "base.py"


# --- Phrase: "`infer` now follows imports to resolve types across files."
#     Context: an imported module value.
def test_infer_imported_module(tmp_path):
    files = {
        "helper.py": '"""Helper docs."""\n',
        "main.py": "import helper\n" + C + "helper\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["type"] == "module"
    assert got["full_name"] == "helper"
    assert got["docstring"] == "Helper docs."


# --- Phrase: "Attribute completion now works for imported names"
#     Context: attributes of an instance of an imported class.
def test_attribute_completion_on_imported_class_instance(tmp_path):
    files = {
        "models.py": "class Widget:\n    def __init__(self):\n"
                     "        self.size = 1\n\n    def render(self):\n"
                     "        pass\n",
        "main.py": "from models import Widget\nw = Widget()\nw." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "render")
    assert entry(data, "size")["description"] == "instance of int"


# --- Phrase: "Attribute completion now works for imported names"
#     Context: attributes of an imported module.
def test_attribute_completion_on_imported_module(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n\n\nCONST = 2\n",
        "main.py": "import helper\nhelper." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert entry(data, "greet")["type"] == "function"
    assert entry(data, "CONST")["description"] == "instance of int"


# --- Phrase: "Attribute completion now works for imported names"
#     Context: attributes on a class imported through a package.
def test_attribute_completion_through_package(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/models.py": "class Widget:\n    def render(self):\n        pass\n",
        "main.py": "from pkg.models import Widget\nWidget." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "render")


# --- Phrase: "Attribute completion now works for imported names"
#     Context: chained attribute access `mod.Class.method`.
def test_attribute_completion_chained(tmp_path):
    files = {
        "models.py": "class Widget:\n    def render(self):\n        pass\n",
        "main.py": "import models\nmodels.Widget." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "render")


# --- Phrase: "`goto` ... returns the actual definition in the source module"
#     Context: goto on an attribute of an imported module needs no flag.
def test_goto_attribute_of_imported_module(tmp_path):
    files = {
        "helper.py": "def greet():\n    pass\n",
        "main.py": "import helper\nhelper.gre" + C + "et()\n",
    }
    got = one(defs_in(tmp_path, files, "goto"))
    assert (got["module_path"], got["line"]) == ("helper.py", 1)
