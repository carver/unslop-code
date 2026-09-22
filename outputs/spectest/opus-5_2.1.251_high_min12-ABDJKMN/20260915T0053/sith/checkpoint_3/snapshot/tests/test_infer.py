"""Spec section: `infer` and the Type Inference Rules."""
from conftest import (CURSOR, infer_at, infer_raw, goto_at, one, dnames)

C = CURSOR


# --- Phrase: "Returns what the name at the cursor position evaluates to."
#     Context: a name bound to an instance of a local class.
def test_infer_name_evaluates_to_instance(tmp_path):
    code = (
        "class Calculator:\n"
        "    pass\n"
        "\n"
        "\n"
        "calc = Calculator()\n"
        "cal" + C + "c\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"], d["line"]) == ("Calculator", "instance", 1)


# --- Phrase: "If the cursor is not on a name, exit 1." (infer, whitespace)
def test_infer_not_on_a_name_whitespace(tmp_path):
    proc = infer_raw(tmp_path, "x = 1\n" + " " + C + "\n")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip()


# --- Phrase: "If the cursor is not on a name, exit 1." (infer, operator)
def test_infer_not_on_a_name_operator(tmp_path):
    proc = infer_raw(tmp_path, "x = 1 " + C + "+ 2\n")
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "If the cursor is not on a name, exit 1." (infer, blank line)
def test_infer_not_on_a_name_blank_line(tmp_path):
    proc = infer_raw(tmp_path, "x = 1\n" + C + "\n")
    assert proc.returncode == 1


# --- Phrase: "If the name cannot be resolved, return an empty array (exit 0)."
def test_infer_unresolvable_name(tmp_path):
    defs = infer_at(tmp_path, "mystery" + C + "_name\n")
    assert defs == []


# --- Phrase: "If the name cannot be resolved, return an empty array (exit 0)."
#     Context: an attribute that does not exist on a known instance.
def test_infer_unknown_attribute(tmp_path):
    code = (
        "class K:\n"
        "    pass\n"
        "\n"
        "\n"
        "k = K()\n"
        "k.nope" + C + "\n"
    )
    assert infer_at(tmp_path, code) == []


# --- Phrase: "infer returns what the name at the cursor evaluates to after static
#     propagation through assignments and calls."
#     Context: propagation through a call.
def test_infer_through_call(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def build():\n"
        "    return Widget()\n"
        "\n"
        "\n"
        "w = build()\n"
        "" + C + "w\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")


# --- Phrase: "For literals, infer returns a definition pointing to the builtin type
#     with module_path set to empty string and line/column set to 0."
def test_infer_literal_types(tmp_path):
    cases = {
        "1": "int",
        "1.5": "float",
        "'text'": "str",
        "True": "bool",
        "[1]": "list",
        "{'a': 1}": "dict",
        "(1, 2)": "tuple",
        "{1, 2}": "set",
        "b'x'": "bytes",
    }
    for literal, typename in cases.items():
        code = "x = %s\n" % literal + "x" + C + "\n"
        d = one(infer_at(tmp_path, code))
        assert d["full_name"] == "builtins." + typename, literal
        assert d["module_path"] == ""
        assert (d["line"], d["column"]) == (0, 0)
        assert d["type"] == "instance"


# --- Phrase: "### Assignments / Follow assignment chains."
def test_infer_assignment_chain(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "a = Widget()\n"
        "b = a\n"
        "c = b\n"
        "" + C + "c\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"], d["line"]) == ("Widget", "instance", 1)


# --- Phrase: "Follow assignment chains."
#     Context: chain of literals.
def test_infer_assignment_chain_literal(tmp_path):
    code = "a = 3\nb = a\nc = b\n" + "c" + C + "\n"
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.int"


# --- Phrase: "Infer a function's return type by analyzing its `return` statements."
def test_infer_return_type(tmp_path):
    code = (
        "def make():\n"
        "    return 42\n"
        "\n"
        "\n"
        "value = make()\n"
        "valu" + C + "e\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.int"


# --- Phrase: "Infer a function's return type by analyzing its `return` statements."
#     Context: returning a local class instance.
def test_infer_return_instance(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def make():\n"
        "    w = Widget()\n"
        "    return w\n"
        "\n"
        "\n"
        "obj = make()\n"
        "ob" + C + "j\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")


# --- Phrase: "If a function has multiple return paths with different types, return
#     all possible types."
def test_infer_multiple_return_types(tmp_path):
    code = (
        "def pick(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 'text'\n"
        "\n"
        "\n"
        "value = pick(True)\n"
        "valu" + C + "e\n"
    )
    defs = infer_at(tmp_path, code)
    assert {d["full_name"] for d in defs} == {"builtins.int", "builtins.str"}


# --- Phrase: "If a function has no `return` statement ... the return type is `None`."
def test_infer_no_return_is_none(tmp_path):
    code = (
        "def noop():\n"
        "    x = 1\n"
        "\n"
        "\n"
        "value = noop()\n"
        "valu" + C + "e\n"
    )
    d = one(infer_at(tmp_path, code))
    assert d["full_name"] == "builtins.None"
    assert d["type"] == "instance"


# --- Phrase: "... or only bare `return`, the return type is `None`."
def test_infer_bare_return_is_none(tmp_path):
    code = (
        "def noop(flag):\n"
        "    if flag:\n"
        "        return\n"
        "    return\n"
        "\n"
        "\n"
        "value = noop(1)\n"
        "valu" + C + "e\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.None"


# --- Phrase: "If a function has multiple return paths with different types"
#     Context: a bare `return` mixed with a valued one contributes None.
def test_infer_mixed_bare_and_valued_return(tmp_path):
    code = (
        "def maybe(flag):\n"
        "    if flag:\n"
        "        return\n"
        "    return 5\n"
        "\n"
        "\n"
        "value = maybe(1)\n"
        "valu" + C + "e\n"
    )
    defs = infer_at(tmp_path, code)
    assert {d["full_name"] for d in defs} == {"builtins.None", "builtins.int"}


# --- Phrase: "### Class Instantiation / infer returns the class definition with
#     type set to "instance"."
def test_infer_instantiation(tmp_path):
    code = (
        "class Calculator:\n"
        '    """Docs."""\n'
        "    pass\n"
        "\n"
        "\n"
        "calc = Calculator()\n"
        "calc" + C + "\n"
    )
    d = one(infer_at(tmp_path, code))
    assert d["name"] == "Calculator"
    assert d["type"] == "instance"
    assert d["full_name"] == "example.Calculator"
    assert d["module_path"] == "example.py"
    assert d["line"] == 1
    assert d["column"] == 6
    assert d["description"] == "instance of Calculator"


# --- Phrase: "For bare function names, both commands may resolve to the same
#     function definition object."
def test_bare_function_name_infer_equals_goto(tmp_path):
    code = (
        "def helper(a):\n"
        "    return a\n"
        "\n"
        "\n"
        "helpe" + C + "r\n"
    )
    assert infer_at(tmp_path, code) == goto_at(tmp_path, code)
    d = one(infer_at(tmp_path, code))
    assert d["type"] == "function"
    assert d["description"] == "def helper(a)"


# --- Phrase: "infer returns what the name at the cursor evaluates to"
#     Context: the cursor sits on the class name of a constructor call, which is the
#     class itself, not an instance.
def test_infer_class_name_is_class(tmp_path):
    code = (
        "class Calculator:\n"
        "    pass\n"
        "\n"
        "\n"
        "calc = Calc" + C + "ulator()\n"
    )
    d = one(infer_at(tmp_path, code))
    assert d["type"] == "class"


# --- Phrase: "### Attribute Access / Infer attributes from instance state when
#     resolvable."
def test_infer_attribute_from_instance_state(tmp_path):
    code = (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.size = 10\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.siz" + C + "e\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.int"


# --- Phrase: "Infer attributes from instance state when resolvable."
#     Context: an attribute holding another class instance.
def test_infer_attribute_instance(tmp_path):
    code = (
        "class Engine:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Car:\n"
        "    def __init__(self):\n"
        "        self.engine = Engine()\n"
        "\n"
        "\n"
        "car = Car()\n"
        "car.engin" + C + "e\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Engine", "instance")


# --- Phrase: "Infer attributes from instance state when resolvable."
#     Context: `self.x` inside a method of the same class.
def test_infer_self_attribute(tmp_path):
    code = (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.size = 10\n"
        "\n"
        "    def show(self):\n"
        "        return self.siz" + C + "e\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.int"


# --- Phrase: "infer answers what value/type that identifier evaluates to at the cursor."
#     Context: `self` is an instance of the enclosing class.
def test_infer_self(tmp_path):
    code = (
        "class Box:\n"
        "    def show(self):\n"
        "        return sel" + C + "f\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Box", "instance")


# --- Phrase: "infer ... after static propagation through assignments and calls."
#     Context: a method call's return value.
def test_infer_method_call_result(tmp_path):
    code = (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return 0\n"
        "\n"
        "\n"
        "calc = Calculator()\n"
        "total = calc.add(1, 2)\n"
        "tota" + C + "l\n"
    )
    assert one(infer_at(tmp_path, code))["full_name"] == "builtins.int"


# --- Phrase: "Returns what the name at the cursor position evaluates to."
#     Context: an imported function resolves into the other module (T34).
def test_infer_imported_name(tmp_path):
    code = "from helper import greet\n\n\ngree" + C + "t\n"
    d = one(infer_at(tmp_path, code,
                     extra={"helper.py": "def greet():\n    return 1\n"}))
    assert d["module_path"] == "helper.py"
    assert d["full_name"] == "helper.greet"
    assert d["line"] == 1
    assert d["type"] == "function"


# --- Phrase: "One of: `module`, ..."
#     Context: inferring an imported module name yields a module definition.
def test_infer_module(tmp_path):
    code = "import helper\n\n\nhelpe" + C + "r\n"
    d = one(infer_at(tmp_path, code, extra={"helper.py": '"""Helper."""\n'}))
    assert d["type"] == "module"
    assert d["name"] == "helper"
    assert d["full_name"] == "helper"
    assert d["module_path"] == "helper.py"
    assert d["docstring"] == "Helper."


# --- Phrase: "One of: ... `param`" / infer of an annotated parameter.
def test_infer_annotated_param(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "def use(w: Widget):\n"
        "    return " + C + "w\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"]) == ("Widget", "instance")


# --- Phrase: "For unresolved branches, return all reachable possibilities."
def test_infer_all_reachable_possibilities(tmp_path):
    code = (
        "class A:\n"
        "    pass\n"
        "\n"
        "\n"
        "class B:\n"
        "    pass\n"
        "\n"
        "\n"
        "def pick(flag):\n"
        "    if flag:\n"
        "        item = A()\n"
        "    else:\n"
        "        item = B()\n"
        "    return ite" + C + "m\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["A", "B"]


# --- Phrase: "For unresolved branches, return all reachable possibilities."
#     Context: an unconditional assignment after the branch wins outright.
def test_infer_later_unconditional_assignment_wins(tmp_path):
    code = (
        "flag = True\n"
        "if flag:\n"
        "    value = 1\n"
        "value = 'text'\n"
        "valu" + C + "e\n"
    )
    assert [d["full_name"] for d in infer_at(tmp_path, code)] == ["builtins.str"]
