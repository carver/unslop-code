"""`goto`: where the name at the cursor was defined."""


# Spec: "`goto` returns where the name at the cursor is assigned or defined
#        (`def`, `class`, assignment, or import binding)."
def test_goto_a_def(goto):
    definition = goto("def helper():\n    pass\n\nhel|per()\n").only
    assert (definition["line"], definition["column"]) == (1, 4)
    assert definition["type"] == "function"


def test_goto_a_class(goto):
    definition = goto("class Widget:\n    pass\n\nWid|get()\n").only
    assert (definition["line"], definition["column"]) == (1, 6)


def test_goto_an_assignment(goto):
    definition = goto("total = 5\nprint(tot|al)\n").only
    assert (definition["line"], definition["column"]) == (1, 0)
    assert definition["type"] == "statement"


def test_goto_an_import_binding(goto):
    definition = goto("import os\nprint(o|s)\n").only
    assert (definition["line"], definition["column"]) == (1, 7)
    assert definition["type"] == "module"


def test_goto_a_from_import_binding(goto):
    definition = goto("from os import getcwd\ngetc|wd()\n").only
    assert (definition["line"], definition["column"]) == (1, 15)
    assert definition["module_path"] == "sample.py"


# Spec: "goto answers where the identifier is defined/assigned at the cursor."
def test_goto_on_the_definition_itself(goto):
    definition = goto("def hel|per():\n    pass\n").only
    assert (definition["line"], definition["column"]) == (1, 4)


def test_goto_a_parameter(goto):
    definition = goto("def helper(alpha, beta):\n    return al|pha\n").only
    assert (definition["line"], definition["column"]) == (1, 11)
    assert definition["type"] == "param"


# Spec: "`goto` returns where the name at the cursor is assigned" -- the most recent
#        assignment before the cursor wins.
def test_goto_uses_the_binding_in_force(goto):
    source = "value = 1\nvalue = 2\nprint(val|ue)\n"
    assert goto(source).only["line"] == 2


# Spec: "Multiple definitions are returned when a name could resolve to more than one
#        thing (e.g., conditional assignments)."
def test_goto_conditional_assignments(goto):
    source = (
        "if flag:\n"
        "    value = 'text'\n"
        "else:\n"
        "    value = 2\n"
        "print(val|ue)\n"
    )
    assert [d["line"] for d in goto(source).definitions] == [2, 4]


# Spec: "goto returns where the name ... is defined" -- attributes included.
def test_goto_a_method(goto):
    source = (
        "class Widget:\n"
        "    def resize(self):\n"
        "        pass\n"
        "\n"
        "w = Widget()\n"
        "w.res|ize()\n"
    )
    definition = goto(source).only
    assert (definition["line"], definition["column"]) == (2, 8)
    assert definition["full_name"] == "sample.Widget.resize"


def test_goto_an_instance_attribute(goto):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.total = 0\n"
        "\n"
        "w = Widget()\n"
        "w.tot|al\n"
    )
    definition = goto(source).only
    assert (definition["line"], definition["column"]) == (3, 13)
    assert definition["full_name"] == "sample.Widget.total"


def test_goto_a_class_attribute(goto):
    source = "class Widget:\n    size = 3\n\nWidget.si|ze\n"
    assert goto(source).only["line"] == 2


# Spec: "If no definition is found, return an empty array (exit 0)."
def test_goto_an_unknown_attribute(goto):
    source = "class Widget:\n    pass\n\nw = Widget()\nw.miss|ing\n"
    assert goto(source).definitions == []


# Spec: "goto answers where the identifier is defined/assigned at the cursor" -- which
#        includes a cursor sitting on a method or class attribute of a class body.
def test_goto_on_a_method_definition(goto):
    source = "class Widget:\n    def res|ize(self):\n        pass\n"
    definition = goto(source).only
    assert (definition["line"], definition["column"]) == (2, 8)
    assert definition["full_name"] == "sample.Widget.resize"


def test_goto_on_a_class_attribute_definition(goto):
    source = "class Widget:\n    si|ze = 3\n"
    assert goto(source).only["full_name"] == "sample.Widget.size"


def test_goto_on_a_nested_class_definition(goto):
    source = "class Outer:\n    class In|ner:\n        pass\n"
    definition = goto(source).only
    assert definition["full_name"] == "sample.Outer.Inner"
    assert definition["column"] == 10
