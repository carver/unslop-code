"""Spec: `infer` and the Type Inference Rules."""


# Spec: "Returns what the name at the cursor position evaluates to."
# "### Literals - For literals, `infer` returns a definition pointing to the
# builtin type with `module_path` set to empty string and `line`/`column` set
# to 0."
def test_literal_int(infer):
    definition = infer("count = 42\ncoun$t\n").only
    assert (definition["name"], definition["full_name"]) == ("int", "builtins.int")
    assert (definition["module_path"], definition["line"], definition["column"]) == ("", 0, 0)


def test_literal_str(infer):
    assert infer("text = 'hello'\ntex$t\n").only["full_name"] == "builtins.str"


def test_literal_list(infer):
    assert infer("items = [1, 2]\nitem$s\n").only["full_name"] == "builtins.list"


def test_literal_dict(infer):
    assert infer("mapping = {}\nmappin$g\n").only["full_name"] == "builtins.dict"


# Spec: "### Assignments - Follow assignment chains."
def test_assignment_chain(infer):
    source = (
        "class Widget:\n"
        "    pass\n"
        "first = Widget()\n"
        "second = first\n"
        "third = second\n"
        "thir$d\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"], definition["line"]) == ("Widget", "instance", 1)


# Spec: "### Class Instantiation - `infer` returns the class definition with
# `type` set to `instance`."
def test_instantiation_returns_the_class_as_an_instance(infer):
    source = (
        "class Calculator:\n"
        "    pass\n"
        "calc = Calculator()\n"
        "cal$c\n"
    )
    definition = infer(source).only
    assert definition["type"] == "instance"
    assert (definition["name"], definition["line"], definition["column"]) == ("Calculator", 1, 6)


# Spec: "### Function Return Types - Infer a function's return type by
# analyzing its `return` statements."
def test_return_type_of_a_function(infer):
    source = (
        "def compute():\n"
        "    return 3\n"
        "value = compute()\n"
        "valu$e\n"
    )
    assert infer(source).only["full_name"] == "builtins.int"


def test_return_type_of_a_constructor_call(infer):
    source = (
        "class Widget:\n"
        "    pass\n"
        "def build():\n"
        "    return Widget()\n"
        "value = build()\n"
        "valu$e\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"]) == ("Widget", "instance")


# Spec: "If a function has multiple return paths with different types, return
# all possible types."
def test_multiple_return_types(infer):
    source = (
        "def compute(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 'text'\n"
        "value = compute(True)\n"
        "valu$e\n"
    )
    assert sorted(item["name"] for item in infer(source).definitions) == ["int", "str"]


# Spec: "If a function has no `return` statement ... the return type is `None`."
def test_function_without_a_return_infers_none(infer):
    source = (
        "def compute():\n"
        "    pass\n"
        "value = compute()\n"
        "valu$e\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["full_name"]) == ("None", "builtins.None")
    assert definition["type"] == "instance"


# Spec: "... or only bare `return`, the return type is `None`."
def test_function_with_a_bare_return_infers_none(infer):
    source = (
        "def compute(flag):\n"
        "    if flag:\n"
        "        return\n"
        "    return\n"
        "value = compute(True)\n"
        "valu$e\n"
    )
    assert infer(source).only["name"] == "None"


# Spec: methods are inferred the same way as functions.
def test_return_type_of_a_method(infer):
    source = (
        "class Calculator:\n"
        "    def total(self):\n"
        "        return 0\n"
        "value = Calculator().total()\n"
        "valu$e\n"
    )
    assert infer(source).only["full_name"] == "builtins.int"


# Spec: "### Attribute Access - Infer attributes from instance state when
# resolvable."
def test_attribute_inferred_from_instance_state(infer):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.title = 'text'\n"
        "widget = Widget()\n"
        "widget.titl$e\n"
    )
    assert infer(source).only["full_name"] == "builtins.str"


def test_attribute_holding_another_instance(infer):
    source = (
        "class Engine:\n"
        "    pass\n"
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.engine = Engine()\n"
        "widget = Widget()\n"
        "widget.engin$e\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"], definition["line"]) == ("Engine", "instance", 1)


# Spec: "infer returns what the name at the cursor evaluates to at the cursor"
# - a bare class name evaluates to the class itself, not to an instance.
def test_bare_class_name_infers_the_class(infer):
    definition = infer("class Widget:\n    pass\nWidge$t\n").only
    assert (definition["type"], definition["description"]) == ("class", "class Widget")


# Spec: "For bare function names, both commands may resolve to the same
# function definition object."
def test_bare_function_name_infers_the_function(infer):
    definition = infer("def compute():\n    return 1\ncomput$e\n").only
    assert (definition["type"], definition["description"]) == ("function", "def compute()")


# Spec: `infer` follows imports through to the imported definition.
def test_infer_an_imported_class(infer):
    definition = infer(
        "from helper import Thing\nvalue = Thing()\nvalu$e\n",
        extra={"helper.py": "class Thing:\n    pass\n"},
    ).only
    assert (definition["module_path"], definition["type"], definition["line"]) == ("helper.py", "instance", 1)


# Spec: `infer` resolves an imported module to the module itself.
def test_infer_an_imported_module(infer):
    definition = infer(
        "import helper\nhelpe$r\n",
        extra={"helper.py": '"""Helpers."""\n'},
    ).only
    assert (definition["name"], definition["type"]) == ("helper", "module")
    assert definition["module_path"] == "helper.py"


# Spec: "If the name cannot be resolved, return an empty array (exit 0)."
def test_unresolvable_call_result(infer):
    source = (
        "def compute(other):\n"
        "    return other()\n"
        "value = compute(1)\n"
        "valu$e\n"
    )
    assert infer(source).definitions == []


# Spec: `self` evaluates to an instance of the enclosing class.
def test_infer_self(infer):
    source = (
        "class Widget:\n"
        "    def render(self):\n"
        "        sel$f\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"], definition["line"]) == ("Widget", "instance", 1)


# Spec: an annotated parameter evaluates to an instance of the annotation.
def test_infer_an_annotated_parameter(infer):
    source = (
        "class Widget:\n"
        "    pass\n"
        "def render(widget: Widget):\n"
        "    widge$t\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"]) == ("Widget", "instance")
