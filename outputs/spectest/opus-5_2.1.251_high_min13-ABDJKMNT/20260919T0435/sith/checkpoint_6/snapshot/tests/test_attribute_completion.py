"""Attribute completion after a `.`."""


# Spec: "When the cursor follows a `.`, return attributes of the value before the dot."
def test_dot_switches_to_attribute_completion(complete):
    source = "import os\nos.|\n"
    names = complete(source).names
    assert "getcwd" in names
    assert "print" not in names


# Spec: "Modules - if `foo` is an imported module, return the module's public names."
def test_module_attributes_are_returned(complete):
    names = complete("import os\nos.|\n").names
    assert {"getcwd", "path", "sep"} <= set(names)


# Spec: "A name is public if it does not start with `_`."
def test_module_attributes_exclude_underscore_names(complete):
    names = complete("import os\nos.|\n").names
    assert not any(n.startswith("_") for n in names)


# Spec: module attributes are typed by the actual object kind.
def test_module_attribute_types(complete):
    result = complete("import os\nos.|\n")
    assert result.by_name("getcwd")["type"] == "function"
    assert result.by_name("path")["type"] == "module"
    assert result.by_name("sep")["type"] == "instance"


# Spec: dotted receivers resolve through submodules.
def test_dotted_module_receiver(complete):
    names = complete("import os\nos.path.|\n").names
    assert "join" in names


# Spec: "Classes - if `foo` is a class, return its methods and class attributes"
def test_class_methods_and_attributes(complete):
    source = (
        "class Widget:\n"
        "    kind = 'w'\n"
        "    def draw(self):\n"
        "        pass\n"
        "Widget.|\n"
    )
    result = complete(source)
    assert {"kind", "draw"} <= set(result.names)
    assert result.by_name("draw")["type"] == "function"
    assert result.by_name("draw")["description"] == "def draw(...)"
    assert result.by_name("kind")["description"] == "instance of str"


# Spec: "(including inherited ones from base classes defined in the same file)"
def test_inherited_attributes_from_in_file_base(complete):
    source = (
        "class Base:\n"
        "    def shared(self):\n"
        "        pass\n"
        "class Child(Base):\n"
        "    def own(self):\n"
        "        pass\n"
        "Child.|\n"
    )
    assert {"shared", "own"} <= set(complete(source).names)


# Spec: "Instances - if `foo` is an instance (from `foo = MyClass()`), return the same
#        attributes as the class ..."
def test_instance_exposes_class_attributes(complete):
    source = (
        "class Widget:\n"
        "    def draw(self):\n"
        "        pass\n"
        "w = Widget()\n"
        "w.|\n"
    )
    assert "draw" in complete(source).names


# Spec: "... plus any attributes assigned in `__init__` via `self.name = ...`."
def test_instance_exposes_init_self_attributes(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.width = 10\n"
        "        self.label = 'hi'\n"
        "    def draw(self):\n"
        "        self.not_in_init = 1\n"
        "w = Widget()\n"
        "w.|\n"
    )
    result = complete(source)
    assert {"width", "label", "draw"} <= set(result.names)
    assert result.by_name("width")["description"] == "instance of int"


# Spec: instances inherit `__init__` attributes from in-file bases too.
def test_instance_inherits_init_attributes(complete):
    source = (
        "class Base:\n"
        "    def __init__(self):\n"
        "        self.base_attr = 1\n"
        "class Child(Base):\n"
        "    pass\n"
        "c = Child()\n"
        "c.|\n"
    )
    assert "base_attr" in complete(source).names


# Spec: "Literals - string/list/dict/set literals expose attributes appropriate to their
#        inferred builtin type."
def test_string_literal_attributes(complete):
    names = complete("'abc'.|\n").names
    assert {"upper", "startswith", "join"} <= set(names)
    assert "append" not in names


def test_list_literal_attributes(complete):
    names = complete("[1, 2].|\n").names
    assert {"append", "extend", "sort"} <= set(names)


def test_dict_literal_attributes(complete):
    names = complete("{'a': 1}.|\n").names
    assert {"keys", "values", "items"} <= set(names)


def test_set_literal_attributes(complete):
    names = complete("{1, 2}.|\n").names
    assert {"add", "union", "discard"} <= set(names)


# Spec: literal-typed variables expose the same builtin attributes.
def test_variable_bound_to_literal_exposes_builtin_attributes(complete):
    source = "text = 'abc'\ntext.|\n"
    assert "upper" in complete(source).names


# Spec: "If there is a prefix after the dot, filter to attributes matching that prefix."
def test_prefix_after_dot_filters(complete):
    result = complete("text = 'abc'\ntext.up|\n")
    assert "upper" in result.names
    assert "lower" not in result.names
    assert result.by_name("upper")["complete"] == "per"


# Spec: "Attribute completion with an empty prefix returns all resolved attributes for the
#        receiver expression and never adds keywords."
def test_attribute_completion_never_includes_keywords(complete):
    for source in ("import os\nos.|\n", "'abc'.|\n", "import os\nos.imp|\n"):
        result = complete(source)
        assert all(c["type"] != "keyword" for c in result.completions)
        assert "import" not in result.names


# Spec: unresolvable receivers yield no completions but still succeed.
def test_unresolvable_receiver_returns_empty_list(complete):
    result = complete("mystery.|\n")
    assert result.returncode == 0
    assert result.completions == []


# Spec: `self` inside a method is an instance of the enclosing class.
def test_self_resolves_to_the_enclosing_class_instance(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.width = 1\n"
        "    def draw(self):\n"
        "        self.|\n"
    )
    assert {"width", "draw"} <= set(complete(source).names)


# Spec: class attributes include dunder methods defined in the class body.
def test_dunder_methods_are_listed_for_classes(complete):
    source = (
        "class Widget:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "Widget.|\n"
    )
    assert "__init__" in complete(source).names
