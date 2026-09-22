"""Name completion: scope resolution, visibility, and prefix extraction."""


# Spec: "When the cursor is in a position where a bare name is expected (not after a `.`),
#        return all names visible at that scope."
def test_bare_name_context_returns_visible_names(complete):
    source = "alpha = 1\nbeta = 2\n|\n"
    names = complete(source).names
    assert {"alpha", "beta"} <= set(names)


# Spec source 1: "Local scope - names assigned or defined in the immediately enclosing
#                 function/method."
def test_local_scope_names_are_visible(complete):
    source = "def outer():\n    local_one = 1\n    local_two = 2\n    |\n"
    names = complete(source).names
    assert {"local_one", "local_two"} <= set(names)


# Spec source 1: function parameters belong to the local scope and are typed `param`.
def test_parameters_are_visible_in_the_function_body(complete):
    source = "def outer(arg_a, arg_b=1, *rest, kw=2, **kwargs):\n    |\n"
    result = complete(source)
    assert {"arg_a", "arg_b", "rest", "kw", "kwargs"} <= set(result.names)
    assert result.by_name("arg_a")["type"] == "param"


# Spec source 2: "Enclosing scopes - names from enclosing functions (for nested
#                 functions/closures)."
def test_enclosing_function_names_are_visible(complete):
    source = (
        "def outer():\n"
        "    captured = 1\n"
        "    def inner():\n"
        "        |\n"
        "    return inner\n"
    )
    assert "captured" in complete(source).names


# Spec source 3: "Global scope - names defined at module level (assignments, function defs,
#                 class defs, imports)."
def test_global_scope_covers_assign_def_class_import(complete):
    source = (
        "import os\n"
        "gvar = 1\n"
        "def gfunc():\n"
        "    pass\n"
        "class GClass:\n"
        "    pass\n"
        "def user():\n"
        "    |\n"
    )
    assert {"os", "gvar", "gfunc", "GClass"} <= set(complete(source).names)


# Spec source 4: "Builtin scope - builtin names provided by Python's `builtins` module."
def test_builtin_names_are_visible(complete):
    names = complete("|\n").names
    assert {"print", "len", "ValueError", "property"} <= set(names)


# Spec: "checked in order" - a nearer binding shadows a farther one (one entry per name).
def test_nearer_scope_shadows_farther_scope(complete):
    source = (
        "shadowed = 1\n"
        "def outer():\n"
        "    shadowed = 2\n"
        "    |\n"
    )
    result = complete(source)
    assert result.names.count("shadowed") == 1
    assert result.by_name("shadowed")["description"] == "instance of int"


def test_local_shadows_builtin(complete):
    source = "def outer():\n    print = 1\n    prin|\n"
    result = complete(source)
    assert result.names.count("print") == 1
    assert result.by_name("print")["type"] == "instance"


# Spec: "A name is visible only if it is defined before the cursor position in the source
#        (for the local and global scopes)."
def test_later_global_is_not_visible(complete):
    source = "|\nlater = 1\n"
    assert "later" not in complete(source).names


def test_later_local_is_not_visible(complete):
    source = "def outer():\n    |\n    later = 1\n"
    assert "later" not in complete(source).names


# Spec: "... (for the local and global scopes)" - enclosing scopes are not position filtered.
def test_enclosing_scope_names_defined_after_the_cursor_are_visible(complete):
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        |\n"
        "    later_in_outer = 1\n"
        "    return inner\n"
    )
    assert "later_in_outer" in complete(source).names


# Spec: "A `def` or `class` statement makes its name visible from the line of the
#        `def`/`class` keyword."
def test_def_is_visible_from_its_own_def_line(complete):
    source = "def helper():\n    pass\n"
    assert "helper" in complete(source, line=1, col=0).names


def test_class_is_visible_from_its_own_class_line(complete):
    source = "class Widget:\n    pass\n"
    assert "Widget" in complete(source, line=1, col=0).names


# Spec: "... from the line of the `def`/`class` keyword" - not from a decorator line above it.
def test_decorated_def_uses_the_def_keyword_line(complete):
    source = "import functools\n\n\n@functools.cache\ndef decorated():\n    pass\n"
    assert "decorated" not in complete(source, line=4, col=0).names
    assert "decorated" in complete(source, line=5, col=0).names


# Spec: "An assignment makes the name visible from the line of the assignment."
def test_assignment_is_visible_from_its_own_line(complete):
    assert "value" in complete("value = 1\n", line=1, col=0).names


# Spec: "If the cursor is partway through typing a name, the partially typed prefix filters
#        completions."
def test_prefix_filters_completions(complete):
    source = "alpha = 1\nbeta = 2\nal|\n"
    names = complete(source).names
    assert "alpha" in names
    assert "beta" not in names


# Spec: "The prefix is determined by scanning backwards from the cursor to the start of the
#        current identifier."
def test_prefix_scans_back_to_identifier_start(complete):
    source = "alpha = 1\nresult = al|\n"
    result = complete(source)
    assert "alpha" in result.names
    assert result.by_name("alpha")["complete"] == "pha"


def test_prefix_stops_at_non_identifier_characters(complete):
    source = "alpha = 1\nvalues = [1, al|]\n"
    assert "alpha" in complete(source).names


def test_digits_and_underscores_are_part_of_the_prefix(complete):
    source = "my_var2 = 1\nmy_var|\n"
    result = complete(source)
    assert result.by_name("my_var2")["complete"] == "2"


# Spec: enclosing class bodies are not part of a method's lookup chain (Python scoping).
def test_class_body_names_are_not_visible_inside_methods(complete):
    source = (
        "class Widget:\n"
        "    class_attr = 1\n"
        "    def method(self):\n"
        "        |\n"
    )
    assert "class_attr" not in complete(source).names


# Spec: the cursor may sit directly in a class body, which is then the local scope.
def test_class_body_is_the_local_scope_for_a_cursor_inside_it(complete):
    source = "class Widget:\n    class_attr = 1\n    |\n"
    assert "class_attr" in complete(source).names


# Spec: "names assigned ... in the immediately enclosing function" - binding forms.
def test_for_with_except_and_walrus_targets_are_bound(complete):
    source = (
        "def outer(seq):\n"
        "    for loop_var in seq:\n"
        "        pass\n"
        "    with open('f') as handle:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as err:\n"
        "        pass\n"
        "    if (walrus := 1):\n"
        "        pass\n"
        "    a_tuple, b_tuple = 1, 2\n"
        "    annotated: int = 3\n"
        "    |\n"
    )
    names = set(complete(source).names)
    assert {"loop_var", "handle", "err", "walrus", "a_tuple", "b_tuple", "annotated"} <= names
