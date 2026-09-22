"""The `type` and `description` fields for each kind of symbol."""


# Spec: "For functions: `def name(...)`."
def test_function_type_and_description(complete):
    completion = complete("def helper(a, b):\n    pass\nhelp|\n").by_name("helper")
    assert completion["type"] == "function"
    assert completion["description"] == "def helper(...)"


# Spec: "For classes: `class Name`."
def test_class_type_and_description(complete):
    completion = complete("class Widget:\n    pass\nWidg|\n").by_name("Widget")
    assert completion["type"] == "class"
    assert completion["description"] == "class Widget"


# Spec: "For imports: `module name`." / "`import os` makes `os` visible as a module."
def test_plain_import_type_and_description(complete):
    completion = complete("import os\no|\n").by_name("os")
    assert completion["type"] == "module"
    assert completion["description"] == "module os"


def test_aliased_import_uses_the_bound_name(complete):
    result = complete("import os.path as osp\nosp|\n")
    completion = result.by_name("osp")
    assert completion["type"] == "module"
    assert completion["description"] == "module osp"


# Spec: "`import os.path` binds `os`."
def test_dotted_import_binds_the_root_package(complete):
    names = complete("import os.path\no|\n").names
    assert "os" in names


# Spec: "For imported names (from import statements), the `type` reflects the imported
#        object's actual kind if inferable (e.g., `function`, `class`, `module`)."
def test_from_import_of_a_function(complete):
    completion = complete("from os import getcwd\ngetc|\n").by_name("getcwd")
    assert completion["type"] == "function"
    assert completion["description"] == "def getcwd(...)"


def test_from_import_of_a_class(complete):
    completion = complete("from decimal import Decimal\nDeci|\n").by_name("Decimal")
    assert completion["type"] == "class"
    assert completion["description"] == "class Decimal"


def test_from_import_of_a_module(complete):
    completion = complete("from os import path\npat|\n").by_name("path")
    assert completion["type"] == "module"
    assert completion["description"] == "module path"


# Spec: "If not inferable, use `statement`."
def test_uninferable_import_is_a_statement(complete):
    completion = complete(
        "from no_such_module_xyz import thing\nthin|\n"
    ).by_name("thing")
    assert completion["type"] == "statement"


# Spec: "For assignments: `instance of <type>` if the right-hand side is a literal ..."
def test_literal_assignment_descriptions(complete):
    source = (
        "s = 'text'\n"
        "n = 42\n"
        "f = 1.5\n"
        "b = True\n"
        "lst = [1]\n"
        "dct = {'a': 1}\n"
        "st = {1}\n"
        "tpl = (1, 2)\n"
        "|\n"
    )
    result = complete(source)
    expected = {
        "s": "str",
        "n": "int",
        "f": "float",
        "b": "bool",
        "lst": "list",
        "dct": "dict",
        "st": "set",
        "tpl": "tuple",
    }
    for name, typename in expected.items():
        assert result.by_name(name)["description"] == f"instance of {typename}"
        assert result.by_name(name)["type"] == "instance"


# Spec: "... a constructor call ..."
def test_constructor_call_assignment(complete):
    source = "class Widget:\n    pass\nw = Widget()\n|\n"
    completion = complete(source).by_name("w")
    assert completion["type"] == "instance"
    assert completion["description"] == "instance of Widget"


def test_builtin_constructor_call_assignment(complete):
    completion = complete("items = list()\n|\n").by_name("items")
    assert completion["description"] == "instance of list"


# Spec: "... or otherwise resolvable to a known type; otherwise `statement`."
def test_unresolvable_assignment_is_a_statement(complete):
    source = "value = unknown_maker()\n|\n"
    completion = complete(source).by_name("value")
    assert completion["type"] == "statement"
    assert completion["description"] == "statement"


# Spec: "If a function has no `return` statement or only bare `return`, the return type
#        is `None`." -- which makes the call resolvable, so the name is an instance.
def test_call_of_a_none_returning_function(complete):
    source = "def maker():\n    pass\nvalue = maker()\n|\n"
    completion = complete(source).by_name("value")
    assert completion["type"] == "instance"
    assert completion["description"] == "instance of None"


def test_alias_of_a_known_instance_is_resolvable(complete):
    source = "first = 'text'\nsecond = first\n|\n"
    assert complete(source).by_name("second")["description"] == "instance of str"


# Spec: annotated assignments name their type.
def test_annotated_assignment_uses_the_annotation(complete):
    source = "count: int\n|\n"
    assert complete(source).by_name("count")["description"] == "instance of int"


# Spec: type `param` for function parameters.
def test_param_type(complete):
    result = complete("def f(alpha):\n    alph|\n")
    assert result.by_name("alpha")["type"] == "param"


# Spec: builtin scope entries are typed by their actual kind.
def test_builtin_kinds(complete):
    result = complete("|\n")
    assert result.by_name("print")["type"] == "function"
    assert result.by_name("print")["description"] == "def print(...)"
    assert result.by_name("ValueError")["type"] == "class"
    assert result.by_name("ValueError")["description"] == "class ValueError"
