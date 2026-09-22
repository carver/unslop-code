"""Tests for `.pyi` stub support and dynamic parameter inference."""

import json

import pytest

from conftest import (find, make_project, names, one, pcomplete, pdefs, pgoto,
                      pinfer, prun, psigs, run_raw, search)


# =====================================================================
# Stub discovery
# =====================================================================

# Spec: "1. `foo.pyi` adjacent to `foo.py` (inline stub)."
def test_inline_stub_adjacent_to_the_module(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "2. A `stubs/` directory in the project root: `stubs/foo.pyi`"
def test_stubs_directory_module_stub(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "stubs/lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "2. A `stubs/` directory in the project root: ... or `stubs/foo/__init__.pyi`."
def test_stubs_directory_package_stub(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "stubs/lib/__init__.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "the tool looks for type stubs in this order: 1. `foo.pyi` adjacent ... 2. A `stubs/` directory"
# Context: the adjacent stub wins.
def test_adjacent_stub_wins_over_stubs_directory(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "lib.pyi": "def make() -> str: ...\n",
        "stubs/lib.pyi": "def make() -> bytes: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "For a module `foo`, the tool looks for type stubs" (T68)
# Context: a module inside a package uses its dotted path under `stubs/`.
def test_stub_for_a_module_inside_a_package(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/lib.py": "def make():\n    return 1\n",
        "stubs/pkg/lib.pyi": "def make() -> str: ...\n",
        "main.py": "import pkg.lib\nvalue = pkg.lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "The tool now recognizes `.pyi` stub files for type information."
# Context: no stub means the inferred behaviour is unchanged.
def test_without_a_stub_the_source_is_used(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["int"]


# =====================================================================
# What the stub supplies
# =====================================================================

# Spec: "`infer` uses return type annotations from the stub."
def test_infer_uses_stub_return_type(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    d = one(pinfer(tmp_path, files, project=True))
    assert d["name"] == "str" and d["type"] == "instance"


# Spec: "Stub annotations take precedence over inferred types."
def test_stub_return_type_beats_the_inferred_one(tmp_path):
    files = {
        "lib.py": "class Runtime:\n    pass\ndef make():\n    return Runtime()\n",
        "lib.pyi": "class Stubbed:\n    pass\ndef make() -> Stubbed: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["Stubbed"]


# Spec: "`signatures` uses parameter annotations from the stub."
def test_signatures_use_stub_parameter_annotations(tmp_path):
    files = {
        "lib.py": "def make(a, b):\n    return 1\n",
        "lib.pyi": "def make(a: int, b: str = 'x') -> None: ...\n",
        "main.py": "import lib\nlib.make(<|>)\n",
    }
    out = psigs(tmp_path, files, project=True)
    assert out[0]["params"] == ["a: int", "b: str='x'"]
    assert out[0]["description"] == "def make(a: int, b: str='x') -> None"


# Spec: "`complete` uses type annotations from the stub for attribute completion."
def test_complete_uses_stub_annotations(tmp_path):
    files = {
        "lib.py": ("class Thing:\n"
                   "    pass\n"
                   "def make():\n"
                   "    return 1\n"),
        "lib.pyi": ("class Thing:\n"
                    "    size: int\n"
                    "def make() -> Thing: ...\n"),
        "main.py": "import lib\nt = lib.make()\nt.<|>\n",
    }
    comps = pcomplete(tmp_path, files, project=True)
    assert "size" in names(comps)


# Spec: "`complete` uses type annotations from the stub for attribute completion."
# Context: a stubbed class attribute keeps its annotated type.
def test_stub_class_attribute_type(tmp_path):
    files = {
        "lib.py": "class Thing:\n    pass\n",
        "lib.pyi": "class Thing:\n    size: int\n",
        "main.py": "from lib import Thing\nt = Thing()\nt.size.<|>\n",
    }
    comps = pcomplete(tmp_path, files, project=True)
    assert "bit_length" in names(comps)


# Spec: "If a stub exists, type information ... comes from the stub."
# Context: the module's runtime-only names stay visible (T66).
def test_runtime_names_survive_a_partial_stub(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\ndef extra():\n    return 2\n",
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nlib.<|>\n",
    }
    comps = pcomplete(tmp_path, files, project=True)
    assert "extra" in names(comps) and "make" in names(comps)


# =====================================================================
# `goto` and stubs
# =====================================================================

# Spec: "The runtime `.py` file is still used for `goto` (source navigation)."
def test_goto_navigates_to_the_py_source(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nlib.ma<|>ke()\n",
    }
    d = one(pgoto(tmp_path, files, project=True))
    assert (d["module_path"], d["line"]) == ("lib.py", 1)


# Spec: "`goto` still navigates to the `.py` source (not the stub), unless the
#        definition only exists in the stub."
def test_goto_falls_back_to_the_stub_for_stub_only_names(tmp_path):
    files = {
        "lib.py": "def make():\n    return 1\n",
        "lib.pyi": "def make() -> str: ...\ndef extra() -> int: ...\n",
        "main.py": "import lib\nlib.ex<|>tra()\n",
    }
    d = one(pgoto(tmp_path, files, project=True))
    assert (d["module_path"], d["line"]) == ("lib.pyi", 2)


# Spec: "unless the definition only exists in the stub"
# Context: a module that has no `.py` at all.
def test_stub_only_module(tmp_path):
    files = {
        "lib.pyi": "def make() -> str: ...\n",
        "main.py": "import lib\nvalue = lib.make()\nval<|>ue\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "`--scope project`: search all `.py` files in the project." (T67)
# Context: stub files are not themselves project sources.
def test_search_ignores_stub_files(tmp_path):
    files = {"lib.py": "def visible():\n    pass\n",
             "lib.pyi": "def visible() -> None: ...\ndef stubonly() -> None: ...\n"}
    assert [d["module_path"] for d in search(tmp_path, files, "visible")] == ["lib.py"]
    assert search(tmp_path, files, "stubonly") == []


# =====================================================================
# Dynamic parameter inference
# =====================================================================

# Spec: "When a function has no type annotations and no stub, the tool can
#        optionally infer parameter types by finding call sites. This is enabled
#        by default and affects `infer` ..."
def test_infer_uses_call_site_argument_types(tmp_path):
    files = {"main.py": ("def f(a):\n"
                         "    return <|>a\n"
                         "f(3)\n")}
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["int"]


# Spec: "infer parameter types by finding call sites"
# Context: a keyword argument at the call site binds by name.
def test_call_site_keyword_argument(tmp_path):
    files = {"main.py": ("def f(a, b):\n"
                         "    return <|>b\n"
                         "f(1, b='x')\n")}
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "infer parameter types by finding call sites"
# Context: a method call site binds arguments after `self`.
def test_call_site_of_a_method(tmp_path):
    files = {"main.py": ("class Box:\n"
                         "    def put(self, item):\n"
                         "        return <|>item\n"
                         "Box().put('x')\n")}
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "Do not search other files for call sites."
def test_call_sites_in_other_files_are_ignored(tmp_path):
    files = {"lib.py": "def f(a):\n    return <|>a\n",
             "main.py": "from lib import f\nf(3)\n"}
    assert pinfer(tmp_path, files, project=True) == []


# Spec: "When a function has no type annotations ..."
# Context: an annotation wins over the call site.
def test_annotation_beats_the_call_site(tmp_path):
    files = {"main.py": ("def f(a: str):\n"
                         "    return <|>a\n"
                         "f(3)\n")}
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "Stub annotations take precedence over inferred types."
# Context: "... and no stub" -- a stub parameter annotation wins over call sites.
def test_stub_parameter_annotation_beats_the_call_site(tmp_path):
    files = {
        "lib.py": "def f(a):\n    return <|>a\nf(3)\n",
        "lib.pyi": "def f(a: str) -> str: ...\n",
        "main.py": "import lib\n",
    }
    assert [d["name"] for d in pinfer(tmp_path, files, project=True)] == ["str"]


# Spec: "infer parameter types by finding call sites"
# Context: no call site leaves the parameter unknown.
def test_parameter_without_call_sites_stays_unknown(tmp_path):
    files = {"main.py": "def f(a):\n    return <|>a\n"}
    assert pinfer(tmp_path, files, project=True) == []


# Spec: "the tool can optionally infer parameter types ... This is enabled by default" (T70)
def test_dynamic_inference_can_be_disabled(tmp_path):
    files = {"main.py": ("def f(a):\n"
                         "    return <|>a\n"
                         "f(3)\n")}
    r = prun("infer", tmp_path, files, extra=["--no-dynamic"], project=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["definitions"] == []
