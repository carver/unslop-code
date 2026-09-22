"""Spec section: Stub File Support (`.pyi`)."""
from conftest import (CURSOR, defs_in, sigs_in, comps_in, one, dnames)

C = CURSOR


# --- Phrase: "For a module `foo`, the tool looks for type stubs in this order:
#     1. `foo.pyi` adjacent to `foo.py` (inline stub)."
def test_inline_stub_is_found(tmp_path):
    files = {
        "lib.py": "def make():\n    return None\n",
        "lib.pyi": "def make() -> int: ...\n",
        "main.py": "import lib\n\nx = lib.make()\n" + C + "x\n",
    }
    d = one(defs_in(tmp_path, files, cmd="infer"))
    assert d["name"] == "int"


# --- Phrase: "2. A `stubs/` directory in the project root: `stubs/foo.pyi`"
def test_stubs_directory_flat(tmp_path):
    files = {
        "lib.py": "def make():\n    return None\n",
        "stubs/lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\n\nx = lib.make()\n" + C + "x\n",
    }
    d = one(defs_in(tmp_path, files, cmd="infer"))
    assert d["name"] == "str"


# --- Phrase: "2. ... or `stubs/foo/__init__.pyi`."
def test_stubs_directory_package(tmp_path):
    files = {
        "lib.py": "def make():\n    return None\n",
        "stubs/lib/__init__.pyi": "def make() -> bytes: ...\n",
        "main.py": "import lib\n\nx = lib.make()\n" + C + "x\n",
    }
    d = one(defs_in(tmp_path, files, cmd="infer"))
    assert d["name"] == "bytes"


# --- Phrase: "the tool looks for type stubs in this order" (adjacent wins)
def test_inline_stub_beats_stubs_directory(tmp_path):
    files = {
        "lib.py": "def make():\n    return None\n",
        "lib.pyi": "def make() -> int: ...\n",
        "stubs/lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\n\nx = lib.make()\n" + C + "x\n",
    }
    assert one(defs_in(tmp_path, files, cmd="infer"))["name"] == "int"


# --- Phrase: "`signatures` uses parameter annotations from the stub."
def test_signatures_use_stub_annotations(tmp_path):
    files = {
        "lib.py": "def greet(name):\n    return name\n",
        "lib.pyi": "def greet(name: str) -> str: ...\n",
        "main.py": "import lib\n\nlib.greet(" + C + ")\n",
    }
    sig = sigs_in(tmp_path, files)[0]
    assert sig["params"] == ["name: str"]
    assert sig["description"] == "def greet(name: str) -> str"


# --- Phrase: "`infer` uses return type annotations from the stub."
def test_infer_uses_stub_return_type(tmp_path):
    files = {
        "lib.py": "def make():\n    return 'text'\n",
        "lib.pyi": "def make() -> int: ...\n",
        "main.py": "from lib import make\n\nx = make()\n" + C + "x\n",
    }
    assert one(defs_in(tmp_path, files, cmd="infer"))["name"] == "int"


# --- Phrase: "Stub annotations take precedence over inferred types."
def test_stub_beats_inference(tmp_path):
    files = {
        "lib.py": "def make():\n    return 'a string'\n",
        "lib.pyi": "def make() -> int: ...\n",
        "main.py": "import lib\n\nx = lib.make()\n" + C + "x\n",
    }
    assert dnames(defs_in(tmp_path, files, cmd="infer")) == ["int"]


# --- Phrase: "`complete` uses type annotations from the stub for attribute
#     completion."
def test_complete_uses_stub_annotations(tmp_path):
    files = {
        "lib.py": "def make():\n    return None\n",
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\n\nx = lib.make()\nx.upp" + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert "upper" in [c["name"] for c in data["completions"]]


# --- Phrase: "class attributes ... come from the stub"
def test_class_attributes_from_stub(tmp_path):
    files = {
        "lib.py": "class Thing:\n    def __init__(self):\n"
                  "        self.size = None\n",
        "lib.pyi": "class Thing:\n    size: int\n",
        "main.py": "import lib\n\nt = lib.Thing()\ny = t.size\n" + C + "y\n",
    }
    assert one(defs_in(tmp_path, files, cmd="infer"))["name"] == "int"


# --- Phrase: "The runtime `.py` file is still used for `goto` (source
#     navigation)." / "`goto` still navigates to the `.py` source (not the
#     stub)"
def test_goto_navigates_to_source(tmp_path):
    files = {
        "lib.py": "def greet(name):\n    return name\n",
        "lib.pyi": "def greet(name: str) -> str: ...\n",
        "main.py": "import lib\n\nlib.gre" + C + "et('x')\n",
    }
    d = one(defs_in(tmp_path, files, cmd="goto"))
    assert (d["module_path"], d["line"], d["column"]) == ("lib.py", 1, 4)


# --- Phrase: "... unless the definition only exists in the stub."
def test_goto_falls_back_to_stub_only_definition(tmp_path):
    files = {
        "lib.py": "def greet(name):\n    return name\n",
        "lib.pyi": "def greet(name: str) -> str: ...\n"
                   "def extra() -> int: ...\n",
        "main.py": "import lib\n\nlib.ext" + C + "ra()\n",
    }
    d = one(defs_in(tmp_path, files, cmd="goto"))
    assert (d["module_path"], d["line"]) == ("lib.pyi", 2)


# --- Phrase: "If a stub exists, type information ... comes from the stub."
#     (an overlay: source-only names still resolve)
def test_source_only_name_still_resolves(tmp_path):
    files = {
        "lib.py": "def greet(name):\n    return name\n\n\n"
                  "def helper():\n    return 5\n",
        "lib.pyi": "def greet(name: str) -> str: ...\n",
        "main.py": "import lib\n\nx = lib.helper()\n" + C + "x\n",
    }
    assert one(defs_in(tmp_path, files, cmd="infer"))["name"] == "int"


# --- Phrase: "`infer` uses return type annotations from the stub." (the
#     definition object still points at the `.py` source)
def test_infer_on_a_stubbed_function_points_at_source(tmp_path):
    files = {
        "lib.py": "def greet(name):\n    return name\n",
        "lib.pyi": "def greet(name: str) -> str: ...\n",
        "main.py": "import lib\n\nf = lib.greet\n" + C + "f\n",
    }
    d = one(defs_in(tmp_path, files, cmd="infer"))
    assert (d["module_path"], d["line"]) == ("lib.py", 1)
