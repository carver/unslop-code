"""Spec section: `goto`."""
from conftest import CURSOR, goto_at, goto_raw, infer_at, one, dnames

C = CURSOR


# --- Phrase: "Returns the location(s) where the name at the cursor was defined."
def test_goto_function_definition(tmp_path):
    code = (
        "def helper(a):\n"
        "    return a\n"
        "\n"
        "\n"
        "helper(1)\n"
        "x = helpe" + C + "r(2)\n"
    )
    d = one(goto_at(tmp_path, code))
    assert (d["name"], d["line"], d["column"]) == ("helper", 1, 4)
    assert d["type"] == "function"


# --- Phrase: "If the cursor is not on a name, exit 1." (goto)
def test_goto_not_on_a_name(tmp_path):
    proc = goto_raw(tmp_path, "x = 1\nx " + C + "\n")
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "If the cursor is not on a name, exit 1." (goto, punctuation)
def test_goto_not_on_a_name_punctuation(tmp_path):
    proc = goto_raw(tmp_path, "def f(a):\n    return a\n\n\nf(" + C + "1)\n")
    assert proc.returncode == 1


# --- Phrase: "If no definition is found, return an empty array (exit 0)."
def test_goto_no_definition(tmp_path):
    assert goto_at(tmp_path, "undefined_thin" + C + "g\n") == []


# --- Phrase: "goto returns where the name at the cursor is assigned or defined
#     (`def`, ...)"
def test_goto_def(tmp_path):
    code = "def target():\n    return 1\n\n\ntarge" + C + "t()\n"
    d = one(goto_at(tmp_path, code))
    assert (d["line"], d["column"], d["type"]) == (1, 4, "function")


# --- Phrase: "... `class` ..."
def test_goto_class(tmp_path):
    code = "class Target:\n    pass\n\n\nTarge" + C + "t()\n"
    d = one(goto_at(tmp_path, code))
    assert (d["line"], d["column"], d["type"]) == (1, 6, "class")


# --- Phrase: "... assignment ..."
def test_goto_assignment(tmp_path):
    code = "count = 10\nprint(coun" + C + "t)\n"
    d = one(goto_at(tmp_path, code))
    assert (d["name"], d["line"], d["column"]) == ("count", 1, 0)
    assert d["type"] == "statement"
    assert d["description"] == "10"


# --- Phrase: "... or import binding)."
def test_goto_import_binding(tmp_path):
    code = "from helper import greet\n\n\ngree" + C + "t()\n"
    d = one(goto_at(tmp_path, code,
                    extra={"helper.py": "def greet():\n    return 1\n"}))
    assert d["module_path"] == "example.py"
    assert (d["line"], d["column"]) == (1, 19)
    assert d["name"] == "greet"


# --- Phrase: "... import binding" with an alias.
def test_goto_aliased_import_binding(tmp_path):
    code = "from helper import greet as hello\n\n\nhell" + C + "o()\n"
    d = one(goto_at(tmp_path, code,
                    extra={"helper.py": "def greet():\n    return 1\n"}))
    assert d["name"] == "hello"
    assert (d["line"], d["column"]) == (1, 28)
    assert d["description"] == "from helper import greet as hello"


# --- Phrase: "goto answers where the identifier is defined/assigned at the cursor."
#     Context: cursor on the definition itself returns that definition.
def test_goto_on_the_definition_itself(tmp_path):
    code = "def targe" + C + "t():\n    return 1\n"
    d = one(goto_at(tmp_path, code))
    assert (d["name"], d["line"], d["column"]) == ("target", 1, 4)


# --- Phrase: "goto answers where the identifier is defined/assigned at the cursor."
#     Context: cursor on the assignment target itself.
def test_goto_on_assignment_target(tmp_path):
    code = "coun" + C + "t = 10\n"
    d = one(goto_at(tmp_path, code))
    assert (d["line"], d["column"]) == (1, 0)


# --- Phrase: "Returns the location(s) where the name at the cursor was defined."
#     Context: a method reached through an instance.
def test_goto_method_through_instance(tmp_path):
    code = (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "\n"
        "\n"
        "calc = Calculator()\n"
        "calc.ad" + C + "d(1, 2)\n"
    )
    d = one(goto_at(tmp_path, code))
    assert (d["name"], d["line"], d["column"]) == ("add", 2, 8)
    assert d["full_name"] == "example.Calculator.add"
    assert d["description"] == "def add(self, a, b)"


# --- Phrase: "Returns the location(s) where the name at the cursor was defined."
#     Context: an attribute assigned in __init__ (T35).
def test_goto_instance_attribute(tmp_path):
    code = (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.size = 10\n"
        "\n"
        "\n"
        "b = Box()\n"
        "print(b.siz" + C + "e)\n"
    )
    d = one(goto_at(tmp_path, code))
    assert (d["name"], d["line"], d["column"]) == ("size", 3, 13)
    assert d["full_name"] == "example.Box.size"


# --- Phrase: "One of: ... `param`"
#     Context: goto on a parameter usage points at the parameter.
def test_goto_param(tmp_path):
    code = (
        "def use(width, height):\n"
        "    return heigh" + C + "t\n"
    )
    d = one(goto_at(tmp_path, code))
    assert d["type"] == "param"
    assert (d["name"], d["line"], d["column"]) == ("height", 1, 15)
    assert d["full_name"] == "example.use.height"


# --- Phrase: "Multiple definitions are returned when a name could resolve to more
#     than one thing (e.g., conditional assignments)."
#     Context: goto reports both assignment sites.
def test_goto_conditional_assignments(tmp_path):
    code = (
        "flag = True\n"
        "if flag:\n"
        "    value = 1\n"
        "else:\n"
        "    value = 2\n"
        "print(valu" + C + "e)\n"
    )
    defs = goto_at(tmp_path, code)
    assert [(d["line"], d["column"]) for d in defs] == [(3, 4), (5, 4)]
    assert dnames(defs) == ["value", "value"]


# --- Phrase: "goto returns where the name at the cursor is assigned"
#     Context: the last assignment before the cursor wins over earlier ones.
def test_goto_last_assignment_wins(tmp_path):
    code = "value = 1\nvalue = 2\nprint(valu" + C + "e)\n"
    d = one(goto_at(tmp_path, code))
    assert d["line"] == 2


# --- Phrase: "goto answers where the identifier is defined/assigned at the cursor."
#     Context: goto stops at the local binding, infer follows through it.
def test_goto_and_infer_differ_for_assignments(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "\n"
        "thing = Widget()\n"
        "thin" + C + "g\n"
    )
    g = one(goto_at(tmp_path, code))
    i = one(infer_at(tmp_path, code))
    assert (g["name"], g["line"], g["type"]) == ("thing", 5, "statement")
    assert (i["name"], i["line"], i["type"]) == ("Widget", 1, "instance")


# --- Phrase: "goto ... where the name at the cursor was defined"
#     Context: a name defined in an enclosing scope, used inside a function.
def test_goto_enclosing_scope(tmp_path):
    code = (
        "TOTAL = 5\n"
        "\n"
        "\n"
        "def use():\n"
        "    return TOTA" + C + "L\n"
    )
    d = one(goto_at(tmp_path, code))
    assert (d["line"], d["column"]) == (1, 0)


# --- Phrase: "If no definition is found, return an empty array (exit 0)."
#     Context: attribute of an unresolvable receiver.
def test_goto_unknown_receiver_attribute(tmp_path):
    assert goto_at(tmp_path, "mystery.attribut" + C + "e\n") == []


# --- Phrase: "Returns the location(s) where the name at the cursor was defined."
#     Context: builtin names have no source location.
def test_goto_builtin(tmp_path):
    defs = goto_at(tmp_path, "le" + C + "n\n")
    d = one(defs)
    assert d["full_name"] == "builtins.len"
    assert (d["module_path"], d["line"], d["column"]) == ("", 0, 0)
