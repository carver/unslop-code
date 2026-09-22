"""Spec section: Completion / 1. Name Completion."""
from conftest import CURSOR, complete_at, entry, has, names

C = CURSOR


# --- Phrase: "When the cursor is in a position where a bare name is expected (not after a `.`),
#              return all names visible at that scope."
#     Context: module level, one global.
def test_bare_name_context_returns_visible_names(tmp_path):
    data = complete_at(tmp_path, "widget = 1\n" + C + "\n")
    assert has(data, "widget")


# --- Phrase: "1. Local scope — names assigned or defined in the immediately enclosing
#              function/method."
#     Context: local variable inside a function.
def test_local_assignment_visible(tmp_path):
    code = "def outer():\n    local_thing = 1\n    " + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "local_thing")


# --- Phrase: "Local scope — names assigned or defined"
#     Context: a nested def is a local name.
def test_local_def_visible(tmp_path):
    code = "def outer():\n    def helper():\n        pass\n    " + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "helper")


# --- Phrase: "Local scope"
#     Context: parameters are local names of the function.
def test_parameters_are_local_names(tmp_path):
    code = "def outer(alpha, beta=2, *args, **kwargs):\n    " + C + "\n"
    data = complete_at(tmp_path, code)
    for n in ("alpha", "beta", "args", "kwargs"):
        assert has(data, n), n


# --- Phrase: "Local scope — ... the immediately enclosing function/method."
#     Context: a sibling function's locals are not visible.
def test_other_functions_locals_not_visible(tmp_path):
    code = (
        "def one():\n"
        "    hidden_local = 1\n"
        "\n"
        "def two():\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert not has(data, "hidden_local")
    assert has(data, "one")


# --- Phrase: "2. Enclosing scopes — names from enclosing functions
#              (for nested functions/closures)."
#     Context: closure variable.
def test_enclosing_function_names_visible(tmp_path):
    code = (
        "def outer():\n"
        "    captured = 1\n"
        "    def inner():\n"
        "        " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "captured")


# --- Phrase: "3. Global scope — names defined at module level
#              (assignments, function defs, class defs, imports)."
#     Context: each module-level binding form, seen from inside a function.
def test_global_scope_sources(tmp_path):
    code = (
        "import os\n"
        "GLOBAL_VALUE = 1\n"
        "\n"
        "def a_function():\n"
        "    pass\n"
        "\n"
        "class AClass:\n"
        "    pass\n"
        "\n"
        "def use():\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    for n in ("os", "GLOBAL_VALUE", "a_function", "AClass"):
        assert has(data, n), n


# --- Phrase: "4. Builtin scope — builtin names provided by Python's builtins module."
#     Context: builtins are always visible.
def test_builtins_visible(tmp_path):
    data = complete_at(tmp_path, C + "\n")
    for n in ("print", "len", "ValueError", "property"):
        assert has(data, n), n


# --- Phrase: "Visible names come from these sources, checked in order"
#     Context: a local shadowing a global appears once, with the local's meaning (T18).
def test_shadowed_name_appears_once_local_wins(tmp_path):
    code = (
        "def shadowed():\n"
        "    pass\n"
        "\n"
        "def outer():\n"
        "    shadowed = 5\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert names(data).count("shadowed") == 1
    assert entry(data, "shadowed")["type"] == "instance"


# --- Phrase: "checked in order" (global shadows builtin)
#     Context: a module-level `print` replaces the builtin entry.
def test_global_shadows_builtin(tmp_path):
    code = "def print(x):\n    pass\n\n" + C + "\n"
    data = complete_at(tmp_path, code)
    assert names(data).count("print") == 1
    assert entry(data, "print")["description"] == "def print(...)"


# --- Phrase: "A name is visible only if it is defined before the cursor position in the source
#              (for the local and global scopes)."
#     Context: a global defined after the cursor line.
def test_global_defined_after_cursor_not_visible(tmp_path):
    code = "before_name = 1\n" + C + "\nafter_name = 2\n"
    data = complete_at(tmp_path, code)
    assert has(data, "before_name")
    assert not has(data, "after_name")


# --- Phrase: "A name is visible only if it is defined before the cursor position"
#     Context: a local defined later in the same function.
def test_local_defined_after_cursor_not_visible(tmp_path):
    code = (
        "def f():\n"
        "    early = 1\n"
        "    " + C + "\n"
        "    late = 2\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "early")
    assert not has(data, "late")


# --- Phrase: "A `def` or `class` statement makes its name visible from the line of the
#              `def`/`class` keyword."
#     Context: a decorated, multi-line def -- the def line, not the body, is what counts.
def test_def_visible_from_def_line(tmp_path):
    code = (
        "def spanning(\n"
        "    a,\n"
        "    b,\n"
        "):\n"
        "    pass\n"
        "\n"
        "spa" + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "spanning")


# --- Phrase: "A `def` or `class` statement makes its name visible from the line of the
#              `def`/`class` keyword." (T3: inclusive)
#     Context: cursor on the very def line.
def test_def_visible_on_its_own_line(tmp_path):
    data = complete_at(tmp_path, "rec" + C + "\ndef recurse():\n    pass\n")
    assert not has(data, "recurse"), "not yet defined above the cursor"
    data2 = complete_at(tmp_path, "def recurse():\n    return recu" + C + "\n")
    assert has(data2, "recurse")


# --- Phrase: "class statement makes its name visible from the line of the ... class keyword"
#     Context: class name at module level.
def test_class_name_visible(tmp_path):
    code = "class Widget:\n    pass\n\nWid" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "Widget")["type"] == "class"


# --- Phrase: "An assignment makes the name visible from the line of the assignment." (T3)
#     Context: cursor on the same line, after the assignment target.
def test_assignment_visible_on_its_own_line(tmp_path):
    data = complete_at(tmp_path, "total = tot" + C + "\n")
    assert has(data, "total")


# --- Phrase: "If the cursor is partway through typing a name, the partially typed prefix
#              filters completions."
#     Context: prefix "wi" filters out non-matching names.
def test_prefix_filters_completions(tmp_path):
    code = "widget = 1\ngadget = 2\nwi" + C + "\n"
    data = complete_at(tmp_path, code)
    assert has(data, "widget")
    assert not has(data, "gadget")


# --- Phrase: "The prefix is determined by scanning backwards from the cursor to the start of
#              the current identifier."
#     Context: the scan stops at a non-identifier character.
def test_prefix_scan_stops_at_non_identifier(tmp_path):
    code = "widget = 1\nresult = wi" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "widget")["complete"] == "dget"


# --- Phrase: "scanning backwards ... to the start of the current identifier"
#     Context: underscores and digits are identifier characters.
def test_prefix_includes_underscores_and_digits(tmp_path):
    code = "my_var2_thing = 1\nmy_var2" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "my_var2_thing")["complete"] == "_thing"


# --- Phrase: "scanning backwards from the cursor"
#     Context: text after the cursor on the same line is irrelevant.
def test_text_after_cursor_ignored(tmp_path):
    code = "widget = 1\nwi" + C + "ZZZ\n"
    data = complete_at(tmp_path, code)
    assert has(data, "widget")


# --- Phrase: "names assigned or defined" (T16: other binding forms)
#     Context: for/with/except/walrus/annotated targets.
def test_other_binding_forms(tmp_path):
    code = (
        "import contextlib\n"
        "def f(seq):\n"
        "    for loop_var in seq:\n"
        "        pass\n"
        "    with contextlib.suppress(ValueError) as ctx_var:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as err_var:\n"
        "        pass\n"
        "    annotated_var: int = 3\n"
        "    if (walrus_var := 4):\n"
        "        pass\n"
        "    a_var, b_var = 1, 2\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    for n in ("loop_var", "ctx_var", "err_var", "annotated_var", "walrus_var",
              "a_var", "b_var"):
        assert has(data, n), n


# --- Phrase: "Local scope" (T25: cursor below the last statement of a function)
#     Context: blank indented line after the body.
def test_cursor_on_blank_line_inside_function(tmp_path):
    code = (
        "def f():\n"
        "    inner_value = 1\n"
        "    " + C + "\n"
        "\n"
        "def g():\n"
        "    other = 2\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "inner_value")


# --- Phrase: "Enclosing scopes — names from enclosing functions" (T5)
#     Context: class bodies are not enclosing scopes for their methods.
def test_class_body_names_not_visible_inside_method(tmp_path):
    code = (
        "class Widget:\n"
        "    class_level = 1\n"
        "\n"
        "    def method(self):\n"
        "        " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert not has(data, "class_level")
    assert has(data, "self")
    assert has(data, "Widget")


# --- Phrase: "Local scope — names assigned or defined in the immediately enclosing ... method"
#     Context: inside a class body itself, class-level names are local.
def test_class_body_names_visible_in_class_body(tmp_path):
    code = (
        "class Widget:\n"
        "    class_level = 1\n"
        "    " + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "class_level")


# --- Phrase: "type ... param"
#     Context: parameters report type "param".
def test_param_type(tmp_path):
    code = "def f(alpha):\n    al" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "alpha")["type"] == "param"


# --- Phrase: "For functions: `def name(...)`."
#     Context: description of a def.
def test_function_description(tmp_path):
    code = "def compute(a, b):\n    pass\n\ncomp" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "compute") == {
        "name": "compute", "complete": "ute", "type": "function",
        "description": "def compute(...)",
    }


# --- Phrase: "For classes: `class Name`."
#     Context: description of a class def.
def test_class_description(tmp_path):
    code = "class Widget:\n    pass\n\nWid" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "Widget") == {
        "name": "Widget", "complete": "get", "type": "class",
        "description": "class Widget",
    }


# --- Phrase: "async def" is still a function definition.
#     Context: async functions.
def test_async_function_is_function(tmp_path):
    code = "async def fetch():\n    pass\n\nfet" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "fetch")["type"] == "function"
    assert entry(data, "fetch")["description"] == "def fetch(...)"


# --- Phrase: "For assignments: `instance of <type>` if the right-hand side is a literal"
#     Context: literal right-hand sides.
def test_assignment_of_literal(tmp_path):
    code = (
        "num_v = 5\n"
        "str_v = 'x'\n"
        "list_v = [1]\n"
        "dict_v = {}\n"
        "set_v = {1}\n"
        "tuple_v = (1, 2)\n"
        "float_v = 1.5\n"
        "bool_v = True\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    expected = {
        "num_v": "int", "str_v": "str", "list_v": "list", "dict_v": "dict",
        "set_v": "set", "tuple_v": "tuple", "float_v": "float", "bool_v": "bool",
    }
    for name, tname in expected.items():
        e = entry(data, name)
        assert e["type"] == "instance", name
        assert e["description"] == "instance of " + tname, name


# --- Phrase: "instance of <type> if the right-hand side is ... a constructor call"
#     Context: user class constructor and builtin constructor.
def test_assignment_of_constructor_call(tmp_path):
    code = (
        "class Widget:\n"
        "    pass\n"
        "\n"
        "w = Widget()\n"
        "d = dict()\n"
        + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert entry(data, "w")["description"] == "instance of Widget"
    assert entry(data, "w")["type"] == "instance"
    assert entry(data, "d")["description"] == "instance of dict"


# --- Phrase: "otherwise `statement`"
#     Context: an unresolvable right-hand side.
def test_assignment_unresolvable_is_statement(tmp_path):
    code = "mystery = some_unknown_thing(1)\n" + C + "\n"
    data = complete_at(tmp_path, code)
    assert entry(data, "mystery") == {
        "name": "mystery", "complete": "mystery", "type": "statement",
        "description": "statement",
    }
