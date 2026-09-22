"""Spec section: resolved ambiguities of `infer` / `goto` (see AMBIGUITIES.md)."""
from conftest import CURSOR, goto_at, infer_at, infer_raw, one

C = CURSOR


# --- Phrase: "If the cursor is not on a name, exit 1." (T29: keywords)
def test_keyword_is_not_a_name(tmp_path):
    proc = infer_raw(tmp_path, "def f():\n    retur" + C + "n 1\n")
    assert proc.returncode == 1


# --- Phrase: "If the cursor is not on a name, exit 1." (T29: number literal)
def test_number_literal_is_not_a_name(tmp_path):
    proc = infer_raw(tmp_path, "x = 12" + C + "3\n")
    assert proc.returncode == 1


# --- Phrase: "For builtin types (including None, ...)" (T29: `None` is a name)
def test_none_keyword_is_a_name(tmp_path):
    d = one(infer_at(tmp_path, "x = Non" + C + "e\n"))
    assert d["full_name"] == "builtins.None"


# --- Phrase: "For builtin types (including None, int, str, etc.)" (T42)
#     Context: a synthesized builtin definition carries no docstring.
def test_builtin_instance_has_no_docstring(tmp_path):
    assert one(infer_at(tmp_path, "x = 1\nx" + C + "\n"))["docstring"] == ""


# --- Phrase: "line | int | 1-based line number of the definition." (T43)
#     Context: a module has no definition line.
def test_module_definition_has_no_line(tmp_path):
    code = "import helper\nhelpe" + C + "r\n"
    d = one(infer_at(tmp_path, code, extra={"helper.py": "x = 1\n"}))
    assert (d["line"], d["column"]) == (0, 0)


# --- Phrase: "description | ... " (T46: parameters)
def test_param_description(tmp_path):
    code = "def use(height):\n    return heigh" + C + "t\n"
    assert one(goto_at(tmp_path, code))["description"] == "param height"


# --- Phrase: "goto ... or import binding" (T32: the binding's own type)
def test_import_binding_type_follows_the_target(tmp_path):
    code = "from helper import greet\ngree" + C + "t\n"
    d = one(goto_at(tmp_path, code,
                    extra={"helper.py": "def greet():\n    return 1\n"}))
    assert d["type"] == "function"
    assert d["full_name"] == "example.greet"


# --- Phrase: "after static propagation through assignments and calls" (T45)
#     Context: a binary operation with one known builtin operand.
def test_binary_operation_keeps_the_known_type(tmp_path):
    code = (
        "def greet(name):\n"
        "    return 'hi ' + name\n"
        "\n"
        "\n"
        "msg = greet('x')\n"
        "ms" + C + "g\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.str"


# --- Phrase: "after static propagation ..." (T45: comparisons are booleans)
def test_comparison_is_bool(tmp_path):
    assert one(infer_at(tmp_path, "flag = 1 < 2\nfla" + C + "g\n"))["full_name"] \
        == "builtins.bool"


# --- Phrase: "after static propagation ..." (T45: parameter defaults)
def test_param_default_drives_inference(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def use(w=Widget()):\n"
        "    return " + C + "w\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")


# --- Phrase: "For unresolved branches, return all reachable possibilities." (T45)
#     Context: a conditional expression is a union.
def test_conditional_expression_union(tmp_path):
    code = "flag = True\nvalue = 1 if flag else 'text'\nvalu" + C + "e\n"
    defs = infer_at(tmp_path, code)
    assert {d["full_name"] for d in defs} == {"builtins.int", "builtins.str"}


# --- Phrase: "Infer attributes from instance state when resolvable." (T44)
#     Context: an attribute assigned differently in two branches of __init__.
def test_instance_attribute_union(tmp_path):
    code = (
        "class Alpha:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Holder:\n"
        "    def __init__(self, flag):\n"
        "        if flag:\n"
        "            self.thing = Alpha()\n"
        "        else:\n"
        "            self.thing = Beta()\n"
        "\n"
        "\n"
        "h = Holder(True)\n"
        "h.thin" + C + "g\n"
    )
    assert [d["name"] for d in infer_at(tmp_path, code)] == ["Alpha", "Beta"]


# --- Phrase: "Sort by (module_path, line, column) ascending."
#     Context: identical definitions are reported once.
def test_duplicate_definitions_collapse(tmp_path):
    code = (
        "flag = True\n"
        "if flag:\n"
        "    value = 1\n"
        "else:\n"
        "    value = 2\n"
        "valu" + C + "e\n"
    )
    assert len(infer_at(tmp_path, code)) == 1


# --- Phrase: "If a function has no `return` statement ..." (T45)
#     Context: a return annotation stands in when there is no return statement.
def test_return_annotation_used_without_return_statement(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def build() -> Widget:\n"
        "    ...\n"
        "\n"
        "\n"
        "w = build()\n"
        "" + C + "w\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")
