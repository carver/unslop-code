"""Spec: Completion / 2. Attribute Completion."""


# Spec: "When the cursor follows a `.`, return attributes of the value before
# the dot." / "Modules - ... return the module's public names."
def test_module_attributes(complete):
    names = complete("import os\nos.$\n").names
    assert {"getcwd", "path", "sep"} <= set(names)


# Spec: "A name is public if it does not start with `_`."
def test_module_attributes_exclude_private_names(complete):
    names = complete("import os\nos.$\n").names
    assert not [name for name in names if name.startswith("_")]


# Spec: attribute chains resolve through submodules.
def test_nested_module_attributes(complete):
    names = complete("import os\nos.path.$\n").names
    assert "join" in names


# Spec: "Classes - ... return its methods and class attributes".
def test_class_methods_and_attributes(complete):
    source = (
        "class Widget:\n"
        "    registry = []\n"
        "    def render(self):\n"
        "        pass\n"
        "Widget.$\n"
    )
    names = complete(source).names
    assert {"registry", "render"} <= set(names)


# Spec: "(including inherited ones from base classes defined in the same file)"
def test_class_inherits_from_same_file_base(complete):
    source = (
        "class Base:\n"
        "    def shared(self):\n"
        "        pass\n"
        "class Child(Base):\n"
        "    def own(self):\n"
        "        pass\n"
        "Child.$\n"
    )
    names = complete(source).names
    assert {"shared", "own"} <= set(names)


# Spec: "Instances - if `foo` is an instance (from `foo = MyClass()`), return
# the same attributes as the class ..."
def test_instance_exposes_class_attributes(complete):
    source = (
        "class Widget:\n"
        "    def render(self):\n"
        "        pass\n"
        "widget = Widget()\n"
        "widget.$\n"
    )
    assert "render" in complete(source).names


# Spec: "... plus any attributes assigned in `__init__` via `self.name = ...`."
def test_instance_exposes_init_attributes(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.title = 'hello'\n"
        "        self.children = []\n"
        "widget = Widget()\n"
        "widget.$\n"
    )
    names = complete(source).names
    assert {"title", "children"} <= set(names)


def test_instance_init_attributes_are_typed(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.title = 'hello'\n"
        "widget = Widget()\n"
        "widget.$\n"
    )
    assert complete(source).by_name("title")["description"] == "instance of str"


def test_instance_inherits_init_attributes(complete):
    source = (
        "class Base:\n"
        "    def __init__(self):\n"
        "        self.shared_attribute = 1\n"
        "class Child(Base):\n"
        "    pass\n"
        "child = Child()\n"
        "child.$\n"
    )
    assert "shared_attribute" in complete(source).names


# Spec: "Literals - string/list/dict/set literals expose attributes
# appropriate to their inferred builtin type."
def test_string_literal_attributes(complete):
    names = complete("'text'.$\n").names
    assert {"upper", "startswith", "join"} <= set(names)


def test_list_literal_attributes(complete):
    names = complete("[1, 2].$\n").names
    assert {"append", "sort"} <= set(names)


def test_dict_literal_attributes(complete):
    names = complete("{'a': 1}.$\n").names
    assert {"keys", "values", "items"} <= set(names)


def test_set_literal_attributes(complete):
    names = complete("{1, 2}.$\n").names
    assert {"add", "union"} <= set(names)


# Spec: literal-typed variables are "resolvable to a known type".
def test_variable_holding_a_literal_exposes_its_type(complete):
    assert "upper" in complete("text = 'value'\ntext.$\n").names


# Spec: "If there is a prefix after the dot, filter to attributes matching
# that prefix."
def test_prefix_after_dot_filters_attributes(complete):
    names = complete("'text'.up$\n").names
    assert names == ["upper"]


def test_prefix_after_dot_sets_complete_text(complete):
    result = complete("'text'.up$\n")
    assert result.by_name("upper")["complete"] == "per"


# Spec: "Keywords are not included in attribute completion (after `.`)."
def test_no_keywords_after_dot(complete):
    items = complete("import os\nos.$\n").items
    assert not [item for item in items if item["type"] == "keyword"]


def test_no_keywords_after_dot_with_prefix(complete):
    names = complete("import os\nos.fo$\n").names
    assert "for" not in names


# Spec: attribute completion on an unresolvable receiver yields nothing.
def test_unknown_receiver_yields_no_completions(complete):
    result = complete("unknown_thing.$\n")
    assert result.code == 0
    assert result.items == []


# Spec: instance attributes are also reachable through `self` inside a method.
def test_self_resolves_to_the_enclosing_class(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.title = 'x'\n"
        "    def render(self):\n"
        "        self.$\n"
    )
    names = complete(source).names
    assert {"title", "render"} <= set(names)


# Spec: a constructor call is itself a resolvable receiver.
def test_call_expression_receiver(complete):
    source = (
        "class Widget:\n"
        "    def render(self):\n"
        "        pass\n"
        "Widget().$\n"
    )
    assert "render" in complete(source).names
