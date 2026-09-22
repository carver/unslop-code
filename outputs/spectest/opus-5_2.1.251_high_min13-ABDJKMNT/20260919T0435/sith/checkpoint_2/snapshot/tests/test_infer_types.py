"""`infer`: what the name at the cursor evaluates to."""


# Spec: "For literals, `infer` returns a definition pointing to the builtin type with
#        `module_path` set to empty string and `line`/`column` set to 0."
def test_literal_assignment_infers_the_builtin_type(infer):
    definition = infer("count = 42\ncou|nt\n").only
    assert definition["name"] == "int"
    assert definition["type"] == "instance"
    assert definition["full_name"] == "builtins.int"
    assert definition["module_path"] == ""
    assert (definition["line"], definition["column"]) == (0, 0)


# Spec: "For builtin types (including None, int, str, etc.) ..."
def test_builtin_literal_types(infer):
    source = (
        "text = 'hello'\n"
        "number = 1.5\n"
        "flag = True\n"
        "items = [1]\n"
        "mapping = {'a': 1}\n"
        "nothing = None\n"
    )
    expected = {
        "text": "str",
        "number": "float",
        "flag": "bool",
        "items": "list",
        "mapping": "dict",
        "nothing": "None",
    }
    for line, (name, typename) in enumerate(expected.items(), start=1):
        definition = infer(source, line=line, col=0).only
        assert definition["name"] == typename
        assert definition["full_name"] == f"builtins.{typename}"


# Spec: "Returns what the name at the cursor position evaluates to." (cursor on a literal)
def test_cursor_on_a_literal(infer):
    assert infer("value = 4|2\n").only["full_name"] == "builtins.int"


# Spec: "### Assignments — Follow assignment chains."
def test_assignment_chain(infer):
    source = "first = 'text'\nsecond = first\nthird = second\nthi|rd\n"
    assert infer(source).only["name"] == "str"


def test_chain_through_a_class_instance(infer):
    source = (
        "class Widget:\n"
        "    pass\n"
        "a = Widget()\n"
        "b = a\n"
        "b|\n"
    )
    definition = infer(source).only
    assert definition["name"] == "Widget"
    assert definition["type"] == "instance"


# Spec: "`infer` returns the class definition with `type` set to `instance`."
def test_instantiation_points_at_the_class(infer):
    source = "class Widget:\n    pass\nw = Widget()\nw|\n"
    definition = infer(source).only
    assert (definition["line"], definition["column"]) == (1, 6)
    assert definition["full_name"] == "sample.Widget"
    assert definition["type"] == "instance"


# Spec: "For bare function names, both commands may resolve to the same function
#        definition object."
def test_bare_function_name_infers_to_the_function(infer, goto):
    source = "def helper(a):\n    return a\nhel|per\n"
    assert infer(source).only == goto(source).only
    assert infer(source).only["type"] == "function"


# Spec: "`infer` answers what value/type that identifier evaluates to at the cursor."
def test_infer_a_class_name_is_the_class(infer):
    definition = infer("class Widget:\n    pass\nWid|get\n").only
    assert definition["type"] == "class"
    assert definition["description"] == "class Widget"


# Spec: "If the name cannot be resolved, return an empty array."
def test_unresolvable_call_result(infer):
    source = "value = undefined_thing()\nval|ue\n"
    assert infer(source).definitions == []


# Spec: a module name evaluates to the module.
def test_infer_a_module(infer):
    definition = infer("import os\n|os\n").only
    assert definition["type"] == "module"
    assert definition["name"] == "os"


# Spec: "infer returns what the name ... evaluates to after static propagation through
#        assignments and calls."
def test_parameter_annotation(infer):
    source = "class Widget:\n    pass\ndef use(w: Widget):\n    return |w\n"
    definition = infer(source).only
    assert definition["name"] == "Widget"
    assert definition["type"] == "instance"


def test_self_is_an_instance_of_the_class(infer):
    source = "class Widget:\n    def method(self):\n        return sel|f\n"
    assert infer(source).only == {
        "name": "Widget",
        "type": "instance",
        "full_name": "sample.Widget",
        "module_path": "sample.py",
        "line": 1,
        "column": 6,
        "description": "instance of Widget",
        "docstring": "",
    }


# Spec: "For bare function names, both commands may resolve to the same function
#        definition object." -- including a method at its own `def`.
def test_infer_on_a_method_definition(infer):
    source = "class Widget:\n    def res|ize(self):\n        pass\n"
    assert infer(source).only["description"] == "def resize(self)"
