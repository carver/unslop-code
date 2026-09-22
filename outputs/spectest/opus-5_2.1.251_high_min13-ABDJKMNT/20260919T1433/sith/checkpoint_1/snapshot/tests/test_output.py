"""Spec: Output Format and Ordering."""

TYPES = {"module", "class", "function", "instance", "statement", "param", "keyword"}


# Spec: every completion object has name/complete/type/description.
def test_completion_object_fields(complete):
    item = complete("value = 1\nval$\n").by_name("value")
    assert list(item) == ["name", "complete", "type", "description"]
    assert all(isinstance(field, str) for field in item.values())


# Spec: "`type` | One of: module, class, function, instance, statement, param,
# keyword."
def test_types_come_from_the_fixed_set(complete):
    source = (
        "import os\n"
        "class Widget:\n"
        "    pass\n"
        "def helper(argument):\n"
        "    widget = Widget()\n"
        "    unknown = missing()\n"
        "    $\n"
    )
    assert {item["type"] for item in complete(source).items} <= TYPES


# Spec: "`name` | The full name of the completion."
def test_name_is_the_full_name(complete):
    assert complete("value = 1\nval$\n").by_name("value")["name"] == "value"


# Spec: "`complete` | ... the name with the already-typed prefix removed."
def test_complete_strips_the_typed_prefix(complete):
    assert complete("value = 1\nval$\n").by_name("value")["complete"] == "ue"


# Spec: "If no prefix, equals `name`."
def test_complete_equals_name_without_prefix(complete):
    item = complete("value = 1\n$\n").by_name("value")
    assert item["complete"] == "value"


# Spec: "When prefix matching is case-insensitive, removal is by character
# count: the first len(prefix) characters of the matched name are stripped
# regardless of case."
def test_complete_strips_by_character_count(complete):
    item = complete("CamelValue = 1\ncamel$\n").by_name("CamelValue")
    assert item["complete"] == "Value"


# Spec example: {"name":"print","complete":"rint","type":"function",
# "description":"def print(...)"}
def test_builtin_function_shape(complete):
    item = complete("p$\n").by_name("print")
    assert item == {
        "name": "print",
        "complete": "rint",
        "type": "function",
        "description": "def print(...)",
    }


# Spec example: {"name":"property","complete":"roperty","type":"class",
# "description":"class property"}
def test_builtin_class_shape(complete):
    item = complete("p$\n").by_name("property")
    assert item == {
        "name": "property",
        "complete": "roperty",
        "type": "class",
        "description": "class property",
    }


# Spec: "For functions: `def name(...)`."
def test_function_description(complete):
    item = complete("def helper():\n    pass\nhelp$\n").by_name("helper")
    assert item["type"] == "function"
    assert item["description"] == "def helper(...)"


# Spec: "For classes: `class Name`."
def test_class_description(complete):
    item = complete("class Widget:\n    pass\nWid$\n").by_name("Widget")
    assert item["type"] == "class"
    assert item["description"] == "class Widget"


# Spec: "For imports: `module name`."
def test_import_description(complete):
    item = complete("import os\no$\n").by_name("os")
    assert item["type"] == "module"
    assert item["description"] == "module os"


def test_aliased_import_description(complete):
    item = complete("import os.path as handy\nhand$\n").by_name("handy")
    assert item["type"] == "module"
    assert item["description"] == "module handy"


# Spec: "For assignments: `instance of <type>` if the right-hand side is a
# literal ..."
def test_literal_assignment_description(complete):
    result = complete("count = 5\ntext = 'hi'\nitems = []\nmapping = {}\n$\n")
    assert result.by_name("count")["description"] == "instance of int"
    assert result.by_name("text")["description"] == "instance of str"
    assert result.by_name("items")["description"] == "instance of list"
    assert result.by_name("mapping")["description"] == "instance of dict"
    assert result.by_name("count")["type"] == "instance"


# Spec: "... a constructor call ..."
def test_constructor_assignment_description(complete):
    source = "class Widget:\n    pass\nwidget = Widget()\nwid$\n"
    item = complete(source).by_name("widget")
    assert item["type"] == "instance"
    assert item["description"] == "instance of Widget"


# Spec: "... otherwise `statement`."
def test_unresolvable_assignment_description(complete):
    item = complete("value = missing_function()\nval$\n").by_name("value")
    assert item["type"] == "statement"
    assert item["description"] == "statement"


# Spec: "For keywords: the keyword itself."
def test_keyword_description(complete):
    assert complete("lamb$\n").by_name("lambda")["description"] == "lambda"


# Spec: "For imported names (from import statements), the `type` reflects the
# imported object's actual kind if inferable (e.g., function, class, module)."
def test_imported_function_type(complete):
    item = complete("from os.path import join\njo$\n").by_name("join")
    assert item["type"] == "function"


def test_imported_class_type(complete):
    item = complete("from collections import OrderedDict\nOrder$\n").by_name("OrderedDict")
    assert item["type"] == "class"


def test_imported_module_type(complete):
    item = complete("from os import path\npat$\n").by_name("path")
    assert item["type"] == "module"


# Spec: "If not inferable, use `statement`."
def test_uninferable_import_type(complete):
    item = complete("from nonexistent_pkg import thing\nthin$\n").by_name("thing")
    assert item["type"] == "statement"


# Spec: parameters are completed with the `param` type.
def test_parameter_type(complete):
    item = complete("def helper(argument):\n    argu$\n").by_name("argument")
    assert item["type"] == "param"


# Spec Ordering: "Public names ... Private names ... Dunder names ...
# Keywords - sorted alphabetically after all names."
def test_ordering_groups(complete):
    source = "zeta = 1\n_alpha = 2\n__beta__ = 3\n$\n"
    names = complete(source).names
    assert names.index("zeta") < names.index("_alpha") < names.index("__beta__")


def test_keywords_come_after_all_names(complete):
    items = complete("zeta = 1\n_alpha = 2\n__beta__ = 3\n$\n").items
    last_name = max(index for index, item in enumerate(items) if item["type"] != "keyword")
    first_keyword = min(index for index, item in enumerate(items) if item["type"] == "keyword")
    assert last_name < first_keyword


# Spec: "sorted alphabetically, case-insensitive" within each group.
def test_public_group_is_alphabetical_case_insensitive(complete):
    source = "Banana = 1\napple = 2\ncherry = 3\n$\n"
    names = complete(source).names
    picked = [name for name in names if name in {"Banana", "apple", "cherry"}]
    assert picked == ["apple", "Banana", "cherry"]


def test_keywords_are_sorted_alphabetically(complete):
    keywords = [item["name"] for item in complete("$\n").items if item["type"] == "keyword"]
    assert keywords == sorted(keywords, key=str.lower)


def test_private_group_is_sorted(complete):
    source = "_zulu = 1\n_alpha = 2\n_$\n"
    names = complete(source).names
    picked = [name for name in names if name in {"_zulu", "_alpha"}]
    assert picked == ["_alpha", "_zulu"]
