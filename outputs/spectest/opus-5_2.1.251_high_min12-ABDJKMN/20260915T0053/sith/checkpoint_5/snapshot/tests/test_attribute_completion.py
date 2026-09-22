"""Spec section: Completion / 2. Attribute Completion."""
from conftest import CURSOR, complete_at, entry, has, names

C = CURSOR


# --- Phrase: "When the cursor follows a `.`, return attributes of the value before the dot."
#     Context: module receiver, empty prefix.
def test_attribute_context_after_dot(tmp_path):
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    assert has(data, "getcwd")
    assert has(data, "path")


# --- Phrase: "Modules — if `foo` is an imported module, return the module's public names."
#     Context: `import os`.
def test_module_attributes(tmp_path):
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    import os as _os
    expected = {n for n in dir(_os) if not n.startswith("_")}
    assert set(names(data)) == expected


# --- Phrase: "A name is public if it does not start with `_`."
#     Context: underscore names of a module are excluded.
def test_module_attributes_exclude_underscore(tmp_path):
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    assert not any(n.startswith("_") for n in names(data))


# --- Phrase: "Modules"
#     Context: an aliased import still resolves to the module.
def test_module_alias(tmp_path):
    data = complete_at(tmp_path, "import os.path as osp\nosp.jo" + C + "\n")
    assert has(data, "join")


# --- Phrase: "Modules" (T23: dotted receiver chain)
#     Context: `os.path.` resolves through the module chain.
def test_dotted_module_chain(tmp_path):
    data = complete_at(tmp_path, "import os\nos.path.jo" + C + "\n")
    assert entry(data, "join")["complete"] == "in"


# --- Phrase: "Classes — if `foo` is a class, return its methods and class attributes"
#     Context: methods and class-level assignments of a local class.
def test_class_attributes(tmp_path):
    code = (
        "class Widget:\n"
        "    size = 10\n"
        "\n"
        "    def render(self):\n"
        "        pass\n"
        "\n"
        "Widget." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "size")
    assert entry(data, "render")["type"] == "function"
    assert entry(data, "render")["description"] == "def render(...)"
    assert entry(data, "size")["description"] == "instance of int"


# --- Phrase: "(including inherited ones from base classes defined in the same file)"
#     Context: single inheritance in the same file.
def test_inherited_class_attributes(tmp_path):
    code = (
        "class Base:\n"
        "    def base_method(self):\n"
        "        pass\n"
        "\n"
        "class Child(Base):\n"
        "    def child_method(self):\n"
        "        pass\n"
        "\n"
        "Child." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "base_method")
    assert has(data, "child_method")


# --- Phrase: "base classes defined in the same file"
#     Context: multi-level inheritance chain.
def test_inherited_attributes_multi_level(tmp_path):
    code = (
        "class A:\n"
        "    a_attr = 1\n"
        "class B(A):\n"
        "    b_attr = 2\n"
        "class D(B):\n"
        "    d_attr = 3\n"
        "\n"
        "D." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    for n in ("a_attr", "b_attr", "d_attr"):
        assert has(data, n), n


# --- Phrase: "Instances — if `foo` is an instance (from `foo = MyClass()`), return the same
#              attributes as the class ..."
#     Context: instance receiver gets the class's members.
def test_instance_gets_class_attributes(tmp_path):
    code = (
        "class Widget:\n"
        "    size = 10\n"
        "\n"
        "    def render(self):\n"
        "        pass\n"
        "\n"
        "w = Widget()\n"
        "w." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "size")
    assert has(data, "render")


# --- Phrase: "... plus any attributes assigned in `__init__` via `self.name = ...`."
#     Context: instance attribute from __init__.
def test_instance_gets_init_attributes(tmp_path):
    code = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.width = 3\n"
        "        self.label = 'hi'\n"
        "\n"
        "w = Widget()\n"
        "w." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert entry(data, "width")["description"] == "instance of int"
    assert entry(data, "label")["description"] == "instance of str"


# --- Phrase: "plus any attributes assigned in `__init__`" (T22)
#     Context: the class form does not expose __init__ instance attributes.
def test_class_receiver_excludes_init_attributes(tmp_path):
    code = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.width = 3\n"
        "\n"
        "Widget." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert not has(data, "width")
    assert has(data, "__init__")


# --- Phrase: "Instances" (T13)
#     Context: `self.` inside a method of the class.
def test_self_attribute_completion(tmp_path):
    code = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.width = 3\n"
        "\n"
        "    def render(self):\n"
        "        self." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "width")
    assert has(data, "render")


# --- Phrase: "Literals — string/list/dict/set literals expose attributes appropriate to their
#              inferred builtin type."
#     Context: a string literal receiver.
def test_string_literal_attributes(tmp_path):
    data = complete_at(tmp_path, "'hello'.up" + C + "\n")
    assert entry(data, "upper")["complete"] == "per"
    assert entry(data, "upper")["type"] == "function"


# --- Phrase: "Literals — ... list ..."
#     Context: a list literal receiver.
def test_list_literal_attributes(tmp_path):
    data = complete_at(tmp_path, "[1, 2, 3].app" + C + "\n")
    assert has(data, "append")


# --- Phrase: "Literals — ... dict ..."
#     Context: a dict literal receiver.
def test_dict_literal_attributes(tmp_path):
    data = complete_at(tmp_path, "{'a': 1}.ke" + C + "\n")
    assert has(data, "keys")


# --- Phrase: "Literals — ... set ..."
#     Context: a set literal receiver.
def test_set_literal_attributes(tmp_path):
    data = complete_at(tmp_path, "{1, 2}.un" + C + "\n")
    assert has(data, "union")


# --- Phrase: "Literals — ... expose attributes appropriate to their inferred builtin type."
#     Context: a name bound to a literal carries the literal's type.
def test_variable_bound_to_literal(tmp_path):
    code = "text = 'hello'\ntext.up" + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "upper")


# --- Phrase: "If there is a prefix after the dot, filter to attributes matching that prefix."
#     Context: module attributes filtered by prefix.
def test_attribute_prefix_filter(tmp_path):
    data = complete_at(tmp_path, "import os\nos.getc" + C + "\n")
    assert has(data, "getcwd")
    assert all(n.lower().startswith("getc") for n in names(data))


# --- Phrase: "If there is a prefix after the dot, filter ..."
#     Context: the `complete` field strips the prefix after a dot too.
def test_attribute_complete_field(tmp_path):
    data = complete_at(tmp_path, "import os\nos.getc" + C + "\n")
    assert entry(data, "getcwd")["complete"] == "wd"


# --- Phrase: "Attribute completion with an empty prefix returns all resolved attributes for the
#              receiver expression"
#     Context: clarifications section.
def test_attribute_empty_prefix_returns_all(tmp_path):
    code = (
        "class Widget:\n"
        "    a_one = 1\n"
        "    b_two = 2\n"
        "\n"
        "Widget." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "a_one") and has(data, "b_two")


# --- Phrase: "return attributes of the value before the dot" (T20)
#     Context: an unresolvable receiver yields zero completions, exit 0.
def test_unresolvable_receiver_is_empty(tmp_path):
    data = complete_at(tmp_path, "unknown_thing." + C + "\n")
    assert data == {"completions": []}


# --- Phrase: "return attributes of the value before the dot" (T23)
#     Context: a constructor call used directly as the receiver.
def test_call_receiver(tmp_path):
    code = (
        "class Widget:\n"
        "    def render(self):\n"
        "        pass\n"
        "\n"
        "Widget().re" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "render")


# --- Phrase: "Classes" (imported class from another module)
#     Context: a class imported from an installed module.
def test_imported_class_receiver(tmp_path):
    data = complete_at(tmp_path, "from decimal import Decimal\nDecimal.fro" + C + "\n")
    assert has(data, "from_float")


# --- Phrase: "type ... One of: module, class, function, instance, ..."
#     Context: module attribute kinds.
def test_module_attribute_types(tmp_path):
    data = complete_at(tmp_path, "import os\nos." + C + "\n")
    assert entry(data, "getcwd")["type"] == "function"
    assert entry(data, "path")["type"] == "module"
    assert entry(data, "error")["type"] == "class"
    assert entry(data, "sep")["type"] == "instance"
    assert entry(data, "sep")["description"] == "instance of str"
    assert entry(data, "path")["description"] == "module path"
    assert entry(data, "error")["description"] == "class error"
