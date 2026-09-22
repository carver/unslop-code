"""Inferring what a call evaluates to from the callee's `return` statements."""


# Spec: "Infer a function's return type by analyzing its `return` statements."
def test_return_type_of_a_literal(infer):
    source = "def make():\n    return 'text'\n\nvalue = make()\nval|ue\n"
    assert infer(source).only["name"] == "str"


def test_return_type_of_an_instance(infer):
    source = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "def make():\n"
        "    return Widget()\n"
        "\n"
        "value = make()\n"
        "val|ue\n"
    )
    definition = infer(source).only
    assert definition["name"] == "Widget"
    assert definition["type"] == "instance"
    assert definition["line"] == 1


# Spec: inference happens "after static propagation through assignments and calls".
def test_call_expression_at_the_cursor(infer):
    source = "def make():\n    return 1\n\nmak|e()\n"
    assert infer(source).only["type"] == "function"


# Spec: "If a function has multiple return paths with different types, return all
#        possible types."
def test_multiple_return_types(infer):
    source = (
        "def make(flag):\n"
        "    if flag:\n"
        "        return 'text'\n"
        "    return 2\n"
        "\n"
        "value = make(1)\n"
        "val|ue\n"
    )
    assert sorted(infer(source).definition_names) == ["int", "str"]


def test_identical_return_types_collapse(infer):
    source = (
        "def make(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return 2\n"
        "\n"
        "value = make(1)\n"
        "val|ue\n"
    )
    assert infer(source).definition_names == ["int"]


# Spec: "If a function has no `return` statement ... the return type is `None`."
def test_no_return_statement_is_none(infer):
    source = "def make():\n    pass\n\nvalue = make()\nval|ue\n"
    definition = infer(source).only
    assert definition["name"] == "None"
    assert definition["full_name"] == "builtins.None"
    assert definition["type"] == "instance"


# Spec: "... or only bare `return`, the return type is `None`."
def test_bare_return_is_none(infer):
    source = "def make(flag):\n    if flag:\n        return\n    return\n\nv = make(1)\n|v\n"
    assert infer(source).definition_names == ["None"]


def test_mixed_bare_and_valued_returns(infer):
    source = (
        "def make(flag):\n"
        "    if flag:\n"
        "        return\n"
        "    return 3\n"
        "\n"
        "v = make(1)\n"
        "|v\n"
    )
    assert sorted(infer(source).definition_names) == ["None", "int"]


# Spec: return types propagate through methods too.
def test_method_return_type(infer):
    source = (
        "class Calculator:\n"
        "    def add(self, x):\n"
        "        return 1\n"
        "\n"
        "c = Calculator()\n"
        "total = c.add(2)\n"
        "tot|al\n"
    )
    assert infer(source).only["name"] == "int"


# Spec: a nested function's returns belong to the nested function only.
def test_nested_function_returns_are_not_borrowed(infer):
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 'text'\n"
        "    return inner\n"
        "\n"
        "value = outer()\n"
        "val|ue\n"
    )
    assert infer(source).only["type"] == "function"
