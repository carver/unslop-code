"""Spec section: cursor handling and robustness for `infer` / `goto`."""
from conftest import (CURSOR, goto_at, goto_raw, infer_at, infer_raw, one,
                      run_raw, write_source)

C = CURSOR


# --- Phrase: "the name at the cursor position"
#     Context: the cursor may sit anywhere inside the identifier, including both ends.
def test_cursor_anywhere_in_the_name(tmp_path):
    base = "def target():\n    return 1\n\n\n"
    results = []
    for i in range(len("target") + 1):
        code = base + "target"[:i] + C + "target"[i:] + "\n"
        results.append(one(goto_at(tmp_path, code)))
    assert all(d == results[0] for d in results)
    assert results[0]["line"] == 1


# --- Phrase: "the name at the cursor position"
#     Context: the cursor picks the attribute, not the receiver, after a dot.
def test_cursor_on_attribute_not_receiver(tmp_path):
    code = (
        "class Box:\n"
        "    def open(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.ope" + C + "n()\n"
    )
    assert one(goto_at(tmp_path, code))["name"] == "open"


# --- Phrase: "the name at the cursor position"
#     Context: the cursor on the receiver resolves the receiver.
def test_cursor_on_receiver(tmp_path):
    code = (
        "class Box:\n"
        "    def open(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "b = Box()\n"
        "" + C + "b.open()\n"
    )
    assert one(infer_at(tmp_path, code))["name"] == "Box"


# --- Phrase: position validation (inherited from the `complete` contract).
#     Context: a line past the end of the file is an error.
def test_line_out_of_range(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    assert run_raw("infer", str(p), 99, 0, cwd=str(tmp_path)).returncode == 1
    assert run_raw("goto", str(p), 99, 0, cwd=str(tmp_path)).returncode == 1


# --- Phrase: position validation.
#     Context: a column past the end of the line is an error.
def test_column_out_of_range(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    assert run_raw("infer", str(p), 1, 40, cwd=str(tmp_path)).returncode == 1
    assert run_raw("goto", str(p), 1, 40, cwd=str(tmp_path)).returncode == 1


# --- Phrase: "If the cursor is not on a name, exit 1."
#     Context: inside a comment there is no name to resolve (T36).
def test_cursor_in_comment(tmp_path):
    proc = infer_raw(tmp_path, "x = 1\n# not a nam" + C + "e\n")
    assert proc.returncode == 1


# --- Phrase: "If the cursor is not on a name, exit 1."
#     Context: inside a string literal there is no name (T36).
def test_cursor_in_string_literal(tmp_path):
    proc = goto_raw(tmp_path, "x = 'hell" + C + "o'\n")
    assert proc.returncode == 1


# --- Phrase: "Returns what the name at the cursor position evaluates to."
#     Context: a file with a syntax error still resolves what it can (T37).
def test_syntax_error_tolerated(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def broken(:\n"
        "    pass\n"
        "\n"
        "\n"
        "w = Widget()\n"
        "" + C + "w\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")


# --- Phrase: "For nested: `module.Class.method`."
#     Context: a local variable inside a function (T39).
def test_full_name_of_local(tmp_path):
    code = (
        "def outer():\n"
        "    local = 1\n"
        "    return loca" + C + "l\n"
    )
    d = one(goto_at(tmp_path, code))
    assert d["full_name"] == "example.outer.local"
    assert d["type"] == "statement"


# --- Phrase: "module_path | File path where the name is defined, relative to the
#     project root."
#     Context: a definition inside a package subdirectory (T40).
def test_module_path_in_subpackage(tmp_path):
    code = "from pkg.mod import thing\n\n\nthin" + C + "g\n"
    defs = infer_at(tmp_path, code, extra={
        "pkg/__init__.py": "",
        "pkg/mod.py": "def thing():\n    return 1\n",
    })
    d = one(defs)
    assert d["module_path"] == "pkg/mod.py"
    assert d["full_name"] == "pkg.mod.thing"


# --- Phrase: "infer answers what value/type that identifier evaluates to at the
#     cursor."
#     Context: the cursor's own line is taken into account for rebinding.
def test_infer_respects_cursor_line(tmp_path):
    code = (
        "class Alpha:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    pass\n"
        "\n"
        "\n"
        "thing = Alpha()\n"
        "thin" + C + "g\n"
        "thing = Beta()\n"
    )
    assert one(infer_at(tmp_path, code))["name"] == "Alpha"
