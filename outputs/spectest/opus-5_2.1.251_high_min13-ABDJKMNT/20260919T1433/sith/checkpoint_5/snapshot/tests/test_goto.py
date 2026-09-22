"""Spec: `goto` - "where the name at the cursor is assigned or defined"."""


# Spec: "`goto` returns where the name at the cursor was defined" - a `def`.
def test_goto_a_function_definition(goto):
    source = (
        "def compute():\n"
        "    pass\n"
        "comput$e()\n"
    )
    definition = goto(source).only
    assert (definition["name"], definition["line"], definition["column"]) == ("compute", 1, 4)


# Spec: "(`def`, `class`, assignment, or import binding)" - a `class`.
def test_goto_a_class_definition(goto):
    source = (
        "class Widget:\n"
        "    pass\n"
        "Widge$t()\n"
    )
    definition = goto(source).only
    assert (definition["name"], definition["line"], definition["column"]) == ("Widget", 1, 6)


# Spec: "(`def`, `class`, assignment, or import binding)" - an assignment.
def test_goto_an_assignment(goto):
    source = (
        "class Widget:\n"
        "    pass\n"
        "widget = Widget()\n"
        "widge$t\n"
    )
    definition = goto(source).only
    assert (definition["name"], definition["line"], definition["column"]) == ("widget", 3, 0)


# Spec: "(`def`, `class`, assignment, or import binding)" - an import binding
# is answered in the file under the cursor, not in the imported module.
def test_goto_an_import_binding(goto):
    definition = goto(
        "import helper\nhelpe$r.Thing\n",
        extra={"helper.py": "class Thing:\n    pass\n"},
    ).only
    assert (definition["line"], definition["column"]) == (1, 7)
    assert definition["module_path"] == "module_under_test.py"


def test_goto_a_from_import_binding(goto):
    definition = goto(
        "from helper import Thing\nThin$g\n",
        extra={"helper.py": "class Thing:\n    pass\n"},
    ).only
    assert (definition["line"], definition["column"]) == (1, 19)
    assert definition["module_path"] == "module_under_test.py"


# Spec: "goto answers where the identifier is defined/assigned at the cursor" -
# the cursor may sit on the definition itself.
def test_goto_on_the_definition_itself(goto):
    definition = goto("def compu$te():\n    pass\n").only
    assert (definition["name"], definition["line"], definition["column"]) == ("compute", 1, 4)


# Spec: goto on a parameter answers with the parameter.
def test_goto_a_parameter(goto):
    definition = goto("def compute(size):\n    siz$e + 1\n").only
    assert (definition["type"], definition["line"], definition["column"]) == ("param", 1, 12)


# Spec: the nearest binding wins, as for completion.
def test_goto_prefers_the_local_binding(goto):
    source = (
        "value = 1\n"
        "def user():\n"
        "    value = 2\n"
        "    valu$e\n"
    )
    assert goto(source).only["line"] == 3


# Spec: "goto returns where the name at the cursor is assigned" - an attribute
# assigned in `__init__`.
def test_goto_an_attribute_assigned_on_self(goto):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.title = 'text'\n"
        "widget = Widget()\n"
        "widget.titl$e\n"
    )
    definition = goto(source).only
    assert (definition["name"], definition["line"], definition["column"]) == ("title", 3, 13)


# Spec: goto on a method reached through an instance lands on the `def`.
def test_goto_a_method_through_an_instance(goto):
    source = (
        "class Widget:\n"
        "    def render(self):\n"
        "        pass\n"
        "widget = Widget()\n"
        "widget.rende$r()\n"
    )
    definition = goto(source).only
    assert (definition["name"], definition["type"], definition["line"]) == ("render", "function", 2)


# Spec: goto crosses files when the receiver comes from another module.
def test_goto_into_another_project_file(goto):
    definition = goto(
        "from helper import Thing\nThing().rende$r()\n",
        extra={"helper.py": "class Thing:\n    def render(self):\n        pass\n"},
    ).only
    assert definition["module_path"] == "helper.py"
    assert (definition["line"], definition["column"]) == (2, 8)


# Spec: "Multiple definitions are returned when a name could resolve to more
# than one thing (e.g., conditional assignments)."
def test_goto_conditional_assignments(goto):
    source = (
        "def pick(flag):\n"
        "    if flag:\n"
        "        value = 1\n"
        "    else:\n"
        "        value = 'text'\n"
        "    valu$e\n"
    )
    assert [item["line"] for item in goto(source).definitions] == [3, 5]


# Spec: "For bare function names, both commands may resolve to the same
# function definition object."
def test_goto_and_infer_agree_on_a_bare_function_name(goto, infer):
    source = "def compute():\n    return 1\ncomput$e\n"
    assert goto(source).definitions == infer(source).definitions


# Spec: "Multiple definitions are returned when a name could resolve to more
# than one thing" - including an attribute reached through a union.
def test_goto_an_attribute_of_a_union(goto):
    source = (
        "class Duck:\n"
        "    def speak(self):\n"
        "        pass\n"
        "class Dog:\n"
        "    def speak(self):\n"
        "        pass\n"
        "def handle(flag):\n"
        "    if flag:\n"
        "        animal = Duck()\n"
        "    else:\n"
        "        animal = Dog()\n"
        "    animal.spea$k()\n"
    )
    assert [item["full_name"] for item in goto(source).definitions] == [
        "module_under_test.Duck.speak",
        "module_under_test.Dog.speak",
    ]
