"""Spec section: Dynamic Parameter Inference."""
from conftest import CURSOR, infer_at, defs_in, dnames, sigs_at

C = CURSOR


# --- Phrase: "When a function has no type annotations and no stub, the tool
#     can optionally infer parameter types by finding call sites. This is
#     enabled by default and affects `infer` ..."
def test_parameter_inferred_from_call_site(tmp_path):
    code = (
        "def f(a):\n"
        "    return " + C + "a\n"
        "\n"
        "\n"
        "f(3)\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["int"]


# --- Phrase: "... by finding call sites." (keyword argument call site)
def test_parameter_inferred_from_keyword_call_site(tmp_path):
    code = (
        "def f(a, b):\n"
        "    return " + C + "b\n"
        "\n"
        "\n"
        "f(1, b='text')\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["str"]


# --- Phrase: "... by finding call sites." (several call sites give a union)
def test_multiple_call_sites_union(tmp_path):
    code = (
        "def f(a):\n"
        "    return " + C + "a\n"
        "\n"
        "\n"
        "f(3)\n"
        "f('x')\n"
    )
    assert sorted(dnames(infer_at(tmp_path, code))) == ["int", "str"]


# --- Phrase: "... by finding call sites." (a method call site skips `self`)
def test_method_call_site(tmp_path):
    code = (
        "class Box:\n"
        "    def put(self, item):\n"
        "        return " + C + "item\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.put(1.5)\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["float"]


# --- Phrase: "When a function has no type annotations ..." (an annotation
#     wins over call sites)
def test_annotation_beats_call_sites(tmp_path):
    code = (
        "def f(a: str):\n"
        "    return " + C + "a\n"
        "\n"
        "\n"
        "f(3)\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["str"]


# --- Phrase: "... and no stub ..." (a stub annotation wins over call sites)
def test_stub_beats_call_sites(tmp_path):
    files = {
        "lib.py": "def f(a):\n    return a\n\n\nf(3)\n",
        "lib.pyi": "def f(a: str) -> str: ...\n",
        "main.py": "import lib\n\nx = lib.f(1)\n" + C + "x\n",
    }
    assert dnames(defs_in(tmp_path, files, cmd="infer")) == ["str"]


# --- Phrase: "Do not search other files for call sites."
def test_call_sites_are_not_searched_across_files(tmp_path):
    files = {
        "lib.py": "def f(a):\n    return " + C + "a\n",
        "main.py": "import lib\n\nlib.f(3)\n",
    }
    assert defs_in(tmp_path, files, cmd="infer") == []


# --- Phrase: "... affects `infer` and `signatures`." — the rendered parameter
#     text still comes from the declaration, so a bare parameter stays bare.
def test_signature_params_stay_source_derived(tmp_path):
    code = (
        "def f(a):\n"
        "    return a\n"
        "\n"
        "\n"
        "f(3)\n"
        "f(" + C + ")\n"
    )
    assert sigs_at(tmp_path, code)[0]["params"] == ["a"]
