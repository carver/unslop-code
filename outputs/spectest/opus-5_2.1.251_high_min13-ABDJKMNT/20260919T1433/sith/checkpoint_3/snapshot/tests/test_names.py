"""Spec: Completion / 1. Name Completion."""


# Spec: "When the cursor is in a position where a bare name is expected
# (not after a `.`), return all names visible at that scope."
def test_bare_name_context_returns_visible_names(complete):
    result = complete("alpha = 1\ndef beta():\n    pass\n$\n")
    assert {"alpha", "beta"} <= set(result.names)


# Spec: "Local scope - names assigned or defined in the immediately enclosing
# function/method."
def test_local_scope_names(complete):
    source = "def outer():\n    local_value = 1\n    loc$\n"
    assert "local_value" in complete(source).names


def test_local_parameters_are_visible(complete):
    source = "def outer(given):\n    giv$\n"
    assert "given" in complete(source).names


# Spec: "Enclosing scopes - names from enclosing functions (for nested
# functions/closures)."
def test_enclosing_function_scope_names(complete):
    source = (
        "def outer():\n"
        "    captured = 1\n"
        "    def inner():\n"
        "        capt$\n"
        "    return inner\n"
    )
    assert "captured" in complete(source).names


# Spec: "Global scope - names defined at module level (assignments, function
# defs, class defs, imports)."
def test_global_scope_names(complete):
    source = (
        "import os\n"
        "module_value = 1\n"
        "def module_function():\n"
        "    pass\n"
        "class ModuleClass:\n"
        "    pass\n"
        "def user():\n"
        "    $\n"
    )
    names = complete(source).names
    assert {"os", "module_value", "module_function", "ModuleClass"} <= set(names)


# Spec: "Builtin scope - builtin names provided by Python's `builtins` module."
def test_builtin_scope_names(complete):
    names = complete("$\n").names
    assert {"print", "property", "len", "Exception"} <= set(names)


# Spec: scopes are "checked in order" - the innermost definition wins.
def test_local_definition_shadows_global(complete):
    source = (
        "shadowed = 1\n"
        "def user():\n"
        "    shadowed = 'text'\n"
        "    shadow$\n"
    )
    assert complete(source).by_name("shadowed")["description"] == "instance of str"


def test_local_definition_shadows_builtin(complete):
    source = "def user():\n    list = 1\n    lis$\n"
    assert complete(source).by_name("list")["type"] == "instance"


# Spec: "A name is visible only if it is defined before the cursor position in
# the source (for the local and global scopes)."
def test_global_defined_after_cursor_is_hidden(complete):
    source = "before_cursor = 1\n$\nafter_cursor = 2\n"
    names = complete(source).names
    assert "before_cursor" in names
    assert "after_cursor" not in names


def test_local_defined_after_cursor_is_hidden(complete):
    source = "def user():\n    early = 1\n    $\n    late = 2\n"
    names = complete(source).names
    assert "early" in names
    assert "late" not in names


# Spec: "A `def` or `class` statement makes its name visible from the line of
# the `def`/`class` keyword."
def test_def_visible_from_its_own_line(complete):
    source = "def helper():\n    pass\ndef user():\n    help$\n"
    assert "helper" in complete(source).names


def test_class_visible_from_its_own_line(complete):
    source = "class Helper:\n    pass\nHelp$\n"
    assert "Helper" in complete(source).names


def test_def_not_visible_before_its_line(complete):
    source = "$\ndef later_function():\n    pass\n"
    assert "later_function" not in complete(source).names


# Spec: "An assignment makes the name visible from the line of the assignment."
def test_assignment_visible_from_its_own_line(complete):
    source = "assigned = 1\nassign$\n"
    assert "assigned" in complete(source).names


# Spec: "If the cursor is partway through typing a name, the partially typed
# prefix filters completions."
def test_prefix_filters_names(complete):
    source = "apple = 1\napricot = 2\nbanana = 3\nap$\n"
    assert sorted(complete(source).names) == ["apple", "apricot"]


# Spec: "The prefix is determined by scanning backwards from the cursor to the
# start of the current identifier."
def test_prefix_scans_back_to_identifier_start(complete):
    source = "alpha = 1\nresult = al$\n"
    result = complete(source)
    assert "alpha" in result.names
    assert result.by_name("alpha")["complete"] == "pha"


def test_prefix_stops_at_non_identifier_character(complete):
    source = "alpha = 1\nvalue = [al$]\n"
    assert "alpha" in complete(source).names


# Spec: enclosing scopes are not restricted to definitions before the cursor.
def test_enclosing_scope_name_defined_after_inner_function(complete):
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        later$\n"
        "    later_value = 1\n"
    )
    assert "later_value" in complete(source).names


# Spec: class body names are the local scope when the cursor sits in one.
def test_class_body_is_the_local_scope(complete):
    source = "class Holder:\n    attribute = 1\n    attr$\n"
    assert "attribute" in complete(source).names


# Spec: methods do not see the class body scope (Python scoping).
def test_class_attribute_not_visible_inside_method(complete):
    source = (
        "class Holder:\n"
        "    attribute = 1\n"
        "    def method(self):\n"
        "        attr$\n"
    )
    assert "attribute" not in complete(source).names
