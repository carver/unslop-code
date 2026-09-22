"""Spec: New Subcommands / `signatures`."""


def only(result):
    """The single signature of an unambiguous answer."""
    assert len(result.signatures) == 1, result.signatures
    return result.signatures[0]


# Spec: "When the cursor is inside a function call's argument list, return the
# function's signature(s) with an indication of which parameter the cursor is
# currently on."
def test_cursor_in_argument_list_returns_the_signature(signatures):
    result = signatures("def add(left, right):\n    return left\n\nadd($)\n")
    assert result.code == 0
    assert only(result)["name"] == "add"


# Spec: "`name` | string | Function or class name."
def test_name_of_a_called_class(signatures):
    result = signatures("class Widget:\n    def __init__(self, size):\n        pass\n\nWidget($)\n")
    assert only(result)["name"] == "Widget"


# Spec: '`params` ... `"name"` for bare parameters'
def test_bare_parameters(signatures):
    result = signatures("def add(left, right):\n    pass\n\nadd($)\n")
    assert only(result)["params"] == ["left", "right"]


# Spec: '`"name: type"` for annotated parameters (one space after colon)'
def test_annotated_parameters(signatures):
    result = signatures("def add(left: int, right: str):\n    pass\n\nadd($)\n")
    assert only(result)["params"] == ["left: int", "right: str"]


# Spec: '`"name=default"` for parameters with defaults (no spaces around `=`)'
def test_defaulted_parameters(signatures):
    result = signatures("def add(left, right=3, label='x'):\n    pass\n\nadd($)\n")
    assert only(result)["params"] == ["left", "right=3", "label='x'"]


# Spec: '`"name: type=default"` for both (no spaces around `=` even with annotation)'
def test_annotated_and_defaulted_parameters(signatures):
    result = signatures("def add(left: int=1):\n    pass\n\nadd($)\n")
    assert only(result)["params"] == ["left: int=1"]


# Spec: 'Special forms: `"*args"`, `"**kwargs"`'
def test_star_parameters(signatures):
    result = signatures("def collect(*args, **kwargs):\n    pass\n\ncollect($)\n")
    assert only(result)["params"] == ["*args", "**kwargs"]


# Spec: 'Special forms: ... `"*args: type"`, `"**kwargs: type"`'
def test_annotated_star_parameters(signatures):
    result = signatures("def collect(*args: int, **kwargs: str):\n    pass\n\ncollect($)\n")
    assert only(result)["params"] == ["*args: int", "**kwargs: str"]


# Spec: "`index` | int or null | 0-based index of the parameter the cursor is
# currently on."
def test_index_of_the_first_parameter(signatures):
    result = signatures("def add(left, right):\n    pass\n\nadd($)\n")
    assert only(result)["index"] == 0


def test_index_follows_the_comma(signatures):
    result = signatures("def add(left, right):\n    pass\n\nadd(1, $)\n")
    assert only(result)["index"] == 1


def test_index_of_a_partly_typed_argument(signatures):
    result = signatures("def add(left, right):\n    pass\n\nadd(1, val$)\n")
    assert only(result)["index"] == 1


# Spec: "`null` if the cursor is past all parameters or in an ambiguous position."
def test_index_is_null_past_the_last_parameter(signatures):
    result = signatures("def add(left, right):\n    pass\n\nadd(1, 2, $)\n")
    assert only(result)["index"] is None


def test_index_is_null_for_a_call_without_parameters(signatures):
    result = signatures("def ready():\n    pass\n\nready($)\n")
    assert only(result)["index"] is None


# Spec: "`description` | string | `\"def name(params)\"` for functions without
# return annotation"
def test_description_without_return_annotation(signatures):
    result = signatures("def add(left, right=2):\n    pass\n\nadd($)\n")
    assert only(result)["description"] == "def add(left, right=2)"


# Spec: 'or `"def name(params) -> ReturnType"` when the function has a return
# type annotation.'
def test_description_with_return_annotation(signatures):
    result = signatures("def add(left: int) -> str:\n    pass\n\nadd($)\n")
    assert only(result)["description"] == "def add(left: int) -> str"


# Spec: "The `self` parameter is excluded for methods."
def test_self_is_excluded_for_methods(signatures):
    source = (
        "class Widget:\n"
        "    def resize(self, amount):\n"
        "        pass\n"
        "\n"
        "Widget().resize($)\n"
    )
    signature = only(signatures(source))
    assert signature["params"] == ["amount"]
    assert signature["description"] == "def resize(amount)"
    assert signature["index"] == 0


# Spec: "`docstring` | string | Function's docstring, or empty string."
def test_docstring_is_reported(signatures):
    result = signatures('def add(left):\n    """Add things."""\n\nadd($)\n')
    assert only(result)["docstring"] == "Add things."


def test_docstring_is_empty_when_absent(signatures):
    result = signatures("def add(left):\n    pass\n\nadd($)\n")
    assert only(result)["docstring"] == ""


# Spec: "Positional arguments map left-to-right to declared positional parameters."
def test_positional_arguments_map_left_to_right(signatures):
    result = signatures("def add(left, middle, right):\n    pass\n\nadd(1, 2, $)\n")
    assert only(result)["index"] == 2


# Spec: "Keyword arguments map to the matching declared parameter when present."
def test_keyword_argument_maps_to_its_parameter(signatures):
    result = signatures("def add(left, middle, right):\n    pass\n\nadd(right=$)\n")
    assert only(result)["index"] == 2


# Spec: "Extra positional arguments map to `*args` when available"
def test_extra_positional_maps_to_var_args(signatures):
    result = signatures("def add(left, *args):\n    pass\n\nadd(1, 2, $)\n")
    assert only(result)["index"] == 1


# Spec: "Extra positional arguments map to `*args` when available, otherwise
# `index` is `null`."
def test_extra_positional_without_var_args_is_null(signatures):
    result = signatures("def add(left):\n    pass\n\nadd(1, 2$)\n")
    assert only(result)["index"] is None


# Spec: "Unknown keyword arguments map to `**kwargs` when available"
def test_unknown_keyword_maps_to_kwargs(signatures):
    result = signatures("def add(left, **kwargs):\n    pass\n\nadd(other=$)\n")
    assert only(result)["index"] == 1


# Spec: "Unknown keyword arguments map to `**kwargs` when available, otherwise
# `index` is `null`."
def test_unknown_keyword_without_kwargs_is_null(signatures):
    result = signatures("def add(left):\n    pass\n\nadd(other=$)\n")
    assert only(result)["index"] is None


# Spec: "If the cursor is not inside a call's parentheses, return an empty
# signatures array (exit 0)."
def test_cursor_outside_a_call_returns_nothing(signatures):
    result = signatures("def add(left):\n    pass\n\nadd\n$\n")
    assert result.code == 0
    assert result.signatures == []


def test_cursor_inside_a_subscript_returns_nothing(signatures):
    result = signatures("values = [1, 2]\nvalues[$]\n")
    assert result.signatures == []


def test_cursor_inside_a_definition_is_not_a_call(signatures):
    result = signatures("def add(left, $):\n    pass\n")
    assert result.signatures == []


def test_unresolvable_callee_returns_nothing(signatures):
    result = signatures("mystery($)\n")
    assert result.code == 0
    assert result.signatures == []


# Spec: "Multiple signatures are returned when the callable has overloads or
# when the name resolves to multiple possible functions. Sort by
# (module_path, line)."
def test_several_possible_functions_are_all_returned(signatures):
    source = (
        "if flag:\n"
        "    def go(alpha):\n"
        "        pass\n"
        "else:\n"
        "    def go(alpha, beta):\n"
        "        pass\n"
        "\n"
        "go($)\n"
    )
    result = signatures(source)
    assert [item["params"] for item in result.signatures] == [["alpha"], ["alpha", "beta"]]
