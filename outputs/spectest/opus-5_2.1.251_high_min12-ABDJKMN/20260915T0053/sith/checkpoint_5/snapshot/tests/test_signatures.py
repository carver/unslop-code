"""Spec section: the `signatures` subcommand — output shape and fields."""
import json

from conftest import CURSOR, sigs_at, sig_raw, sigs_in, write_source, run_raw

C = CURSOR


# --- Phrase: "python sith.py signatures <file> <line> <col>" — the command
#     exists, exits 0 and prints a `signatures` array.
def test_signatures_command_exists(tmp_path):
    code = "def f(a):\n    return a\n\n\nf(" + C + ")\n"
    proc = sig_raw(tmp_path, code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"signatures"}
    assert isinstance(data["signatures"], list)


# --- Phrase: "When the cursor is inside a function call's argument list,
#     return the function's signature(s)"
def test_signature_inside_call(tmp_path):
    code = "def greet(name):\n    return name\n\n\ngreet(" + C + ")\n"
    sigs = sigs_at(tmp_path, code)
    assert len(sigs) == 1
    assert sigs[0]["name"] == "greet"


# --- Phrase: "name | string | Function or class name."
def test_signature_name_is_the_function_name(tmp_path):
    code = "def compute(a, b):\n    return a\n\n\ncompute(1, " + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["name"] == "compute"


# --- Phrase: "name | ... or class name." (a class callable reports the class)
def test_signature_name_of_a_class(tmp_path):
    code = (
        "class Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "\n"
        "\n"
        "Point(" + C + ")\n"
    )
    sig = sigs_at(tmp_path, code)[0]
    assert sig["name"] == "Point"
    assert sig["params"] == ["x", "y"]


# --- Phrase: "params | array of string | ... `\"name\"` for bare parameters"
def test_params_bare(tmp_path):
    code = "def f(a, b, c):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["params"] == ["a", "b", "c"]


# --- Phrase: "`\"name: type\"` for annotated parameters (one space after colon)"
def test_params_annotated(tmp_path):
    code = "def f(a: int, b: str):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["params"] == ["a: int", "b: str"]


# --- Phrase: "`\"name=default\"` for parameters with defaults (no spaces
#     around `=`)"
def test_params_default(tmp_path):
    code = "def f(a, b=3, c='x'):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["params"] == ["a", "b=3", "c='x'"]


# --- Phrase: "`\"name: type=default\"` for both (no spaces around `=` even
#     with annotation)"
def test_params_annotated_default(tmp_path):
    code = "def f(a: int = 3, b: str = 'z'):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["params"] == ["a: int=3", "b: str='z'"]


# --- Phrase: "Special forms: `\"*args\"`, `\"**kwargs\"`"
def test_params_star_forms(tmp_path):
    code = "def f(a, *args, **kwargs):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["params"] == ["a", "*args", "**kwargs"]


# --- Phrase: "Special forms: ... `\"*args: type\"`, `\"**kwargs: type\"`"
def test_params_star_forms_annotated(tmp_path):
    code = ("def f(*args: int, **kwargs: str):\n    return 1\n\n\n"
            "f(" + C + ")\n")
    assert sigs_at(tmp_path, code)[0]["params"] == ["*args: int",
                                                    "**kwargs: str"]


# --- Phrase: "description | ... `\"def name(params)\"` for functions without
#     return annotation"
def test_description_without_return_annotation(tmp_path):
    code = "def f(a, b=2):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["description"] == "def f(a, b=2)"


# --- Phrase: "... or `\"def name(params) -> ReturnType\"` when the function
#     has a return type annotation."
def test_description_with_return_annotation(tmp_path):
    code = ("def f(a: int) -> str:\n    return ''\n\n\nf(" + C + ")\n")
    assert sigs_at(tmp_path, code)[0]["description"] == \
        "def f(a: int) -> str"


# --- Phrase: "The `self` parameter is excluded for methods."
def test_self_excluded_for_methods(tmp_path):
    code = (
        "class Box:\n"
        "    def put(self, item, count=1):\n"
        "        return item\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.put(" + C + ")\n"
    )
    sig = sigs_at(tmp_path, code)[0]
    assert sig["params"] == ["item", "count=1"]
    assert sig["description"] == "def put(item, count=1)"


# --- Phrase: "The `self` parameter is excluded for methods." (index counts
#     the self-less list)
def test_self_excluded_affects_index(tmp_path):
    code = (
        "class Box:\n"
        "    def put(self, item, count=1):\n"
        "        return item\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.put(" + C + ")\n"
    )
    assert sigs_at(tmp_path, code)[0]["index"] == 0


# --- Phrase: "docstring | string | Function's docstring, or empty string."
def test_docstring_present(tmp_path):
    code = (
        "def f(a):\n"
        "    \"\"\"Does a thing.\"\"\"\n"
        "    return a\n"
        "\n"
        "\n"
        "f(" + C + ")\n"
    )
    assert sigs_at(tmp_path, code)[0]["docstring"] == "Does a thing."


# --- Phrase: "docstring | ... or empty string."
def test_docstring_absent_is_empty_string(tmp_path):
    code = "def f(a):\n    return a\n\n\nf(" + C + ")\n"
    assert sigs_at(tmp_path, code)[0]["docstring"] == ""


# --- Phrase: the four fields are exactly the documented set.
def test_signature_fields(tmp_path):
    code = "def f(a):\n    return a\n\n\nf(" + C + ")\n"
    assert set(sigs_at(tmp_path, code)[0]) == {
        "name", "params", "index", "description", "docstring"}


# --- Phrase: "If the cursor is not inside a call's parentheses, return an
#     empty signatures array (exit 0)."
def test_not_inside_a_call(tmp_path):
    code = "def f(a):\n    return a\n\n\nx = 1" + C + "\n"
    assert sigs_at(tmp_path, code) == []


# --- Phrase: "If the cursor is not inside a call's parentheses ..." (a `def`
#     header is not a call)
def test_def_header_is_not_a_call(tmp_path):
    code = "def f(a" + C + "):\n    return a\n"
    assert sigs_at(tmp_path, code) == []


# --- Phrase: "If the cursor is not inside a call's parentheses ..."
#     (grouping parentheses)
def test_grouping_parentheses_are_not_a_call(tmp_path):
    code = "x = (1 + " + C + "2)\n"
    assert sigs_at(tmp_path, code) == []


# --- Phrase: "If the cursor is not inside a call's parentheses ..." (after the
#     closing paren)
def test_after_the_closing_paren(tmp_path):
    code = "def f(a):\n    return a\n\n\nf(1)" + C + "\n"
    assert sigs_at(tmp_path, code) == []


# --- Phrase: "If the cursor is not inside a call's parentheses ..."
#     (a list literal inside a call is not the call's parentheses)
def test_bracket_inside_call(tmp_path):
    code = "def f(a):\n    return a\n\n\nf([1, " + C + "])\n"
    assert sigs_at(tmp_path, code) == []


# --- Phrase: cursor inside a *nested* call reports the inner callable.
def test_nested_call_reports_inner(tmp_path):
    code = (
        "def outer(a):\n    return a\n\n\n"
        "def inner(b):\n    return b\n\n\n"
        "outer(inner(" + C + "))\n"
    )
    sigs = sigs_at(tmp_path, code)
    assert [s["name"] for s in sigs] == ["inner"]


# --- Phrase: cursor after a completed nested call is back on the outer call.
def test_after_nested_call_reports_outer(tmp_path):
    code = (
        "def outer(a, b):\n    return a\n\n\n"
        "def inner(b):\n    return b\n\n\n"
        "outer(inner(1), " + C + ")\n"
    )
    sigs = sigs_at(tmp_path, code)
    assert [s["name"] for s in sigs] == ["outer"]
    assert sigs[0]["index"] == 1


# --- Phrase: "Multiple signatures are returned when ... the name resolves to
#     multiple possible functions."
def test_multiple_possible_functions(tmp_path):
    code = (
        "import random\n"
        "\n"
        "if random.random() > 0.5:\n"
        "    def act(a):\n"
        "        return a\n"
        "else:\n"
        "    def act(a, b):\n"
        "        return b\n"
        "\n"
        "\n"
        "act(" + C + ")\n"
    )
    sigs = sigs_at(tmp_path, code)
    assert [s["params"] for s in sigs] == [["a"], ["a", "b"]]


# --- Phrase: "Multiple signatures are returned when the callable has
#     overloads"
def test_overloads(tmp_path):
    code = (
        "from typing import overload\n"
        "\n"
        "\n"
        "@overload\n"
        "def conv(a: int) -> int: ...\n"
        "@overload\n"
        "def conv(a: str) -> str: ...\n"
        "def conv(a):\n"
        "    return a\n"
        "\n"
        "\n"
        "conv(" + C + ")\n"
    )
    sigs = sigs_at(tmp_path, code)
    assert [s["params"] for s in sigs] == [["a: int"], ["a: str"]]


# --- Phrase: "Sort by `(module_path, line)`."
def test_sort_by_module_path_then_line(tmp_path):
    files = {
        "beta.py": "def run(b):\n    return b\n",
        "alpha.py": "def run(a):\n    return a\n",
        "main.py": (
            "import random\n"
            "from alpha import run\n"
            "from beta import run as run2\n"
            "\n"
            "target = run if random.random() else run2\n"
            "target(" + C + ")\n"
        ),
    }
    sigs = sigs_in(tmp_path, files)
    assert [s["params"] for s in sigs] == [["a"], ["b"]]


# --- Phrase: `signatures` accepts `--project <dir>`.
def test_signatures_project_flag(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "lib.py").write_text("def fn(x, y):\n    return x\n")
    src = "from pkg.lib import fn\nfn(1, )\n"
    path = write_source(tmp_path / "pkg", src, "use.py")
    proc = run_raw("signatures", str(path), 2, 6, "--project", str(tmp_path),
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    sigs = json.loads(proc.stdout)["signatures"]
    assert [s["name"] for s in sigs] == ["fn"]
