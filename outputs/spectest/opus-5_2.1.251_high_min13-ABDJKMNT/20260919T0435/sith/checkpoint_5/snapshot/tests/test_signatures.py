"""`signatures`: the callable under the cursor and how it is rendered."""


# "When the cursor is inside a function call's argument list, return the
#  function's signature(s)"
def test_reports_the_called_function(signatures):
    result = signatures(
        """
def greet(name, greeting):
    return greeting

greet(|)
"""
    )
    assert result.signature["name"] == "greet"


# "| `params` | array of string | Parameter representations. |"
def test_lists_every_parameter(signatures):
    result = signatures(
        """
def greet(name, greeting):
    return greeting

greet(|)
"""
    )
    assert result.signature["params"] == ["name", "greeting"]


# "`\"name\"` for bare parameters"
def test_bare_parameter_is_just_its_name(signatures):
    result = signatures("def f(value):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["value"]


# "`\"name: type\"` for annotated parameters (one space after colon)"
def test_annotated_parameter_uses_one_space_after_the_colon(signatures):
    result = signatures("def f(value: int):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["value: int"]


# "`\"name=default\"` for parameters with defaults (no spaces around `=`)"
def test_default_has_no_spaces_around_the_equals(signatures):
    result = signatures("def f(value = 3):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["value=3"]


# "`\"name: type=default\"` for both (no spaces around `=` even with annotation)"
def test_annotation_and_default_together(signatures):
    result = signatures("def f(value: int = 3):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["value: int=3"]


# "Special forms: `\"*args\"`, `\"**kwargs\"`"
def test_star_parameters_keep_their_stars(signatures):
    result = signatures("def f(a, *args, **kwargs):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["a", "*args", "**kwargs"]


# "Special forms: ... `\"*args: type\"`, `\"**kwargs: type\"`"
def test_annotated_star_parameters(signatures):
    result = signatures("def f(*args: int, **kwargs: str):\n    pass\n\nf(|)\n")
    assert result.signature["params"] == ["*args: int", "**kwargs: str"]


# "| `description` | string | `\"def name(params)\"` for functions without
#  return annotation"
def test_description_without_return_annotation(signatures):
    result = signatures("def f(a, b=2):\n    pass\n\nf(|)\n")
    assert result.signature["description"] == "def f(a, b=2)"


# "or `\"def name(params) -> ReturnType\"` when the function has a return type
#  annotation"
def test_description_with_return_annotation(signatures):
    result = signatures("def f(a: int) -> str:\n    return ''\n\nf(|)\n")
    assert result.signature["description"] == "def f(a: int) -> str"


# "The `self` parameter is excluded for methods."
def test_self_is_excluded_from_a_method_description(signatures):
    result = signatures(
        """
class Box:
    def put(self, item):
        pass

Box().put(|)
"""
    )
    assert result.signature["description"] == "def put(item)"
    assert result.signature["params"] == ["item"]


# "| `docstring` | string | Function's docstring, or empty string. |"
def test_docstring_is_reported(signatures):
    result = signatures(
        """
def f(a):
    \"\"\"Do a thing.\"\"\"

f(|)
"""
    )
    assert result.signature["docstring"] == "Do a thing."


def test_docstring_is_empty_when_absent(signatures):
    result = signatures("def f(a):\n    pass\n\nf(|)\n")
    assert result.signature["docstring"] == ""


# "If the cursor is not inside a call's parentheses, return an empty signatures
#  array (exit 0)."
def test_outside_a_call_returns_nothing(signatures):
    result = signatures("def f(a):\n    pass\n\nva|lue = 1\n")
    assert result.returncode == 0
    assert result.signatures == []


def test_a_list_display_is_not_a_call(signatures):
    result = signatures("numbers = [1, |]\n")
    assert result.signatures == []


# "Multiple signatures are returned when ... the name resolves to multiple
#  possible functions.  Sort by `(module_path, line)`."
def test_multiple_functions_sorted_by_line(signatures):
    result = signatures(
        """
flag = True
if flag:
    def handle(first):
        pass
else:
    def handle(second, third):
        pass

handle(|)
"""
    )
    assert [s["params"] for s in result.signatures] == [["first"], ["second", "third"]]


# "Multiple signatures are returned when the callable has overloads"
def test_overloads_are_all_returned(signatures):
    result = signatures(
        """
from typing import overload

@overload
def load(path: str) -> str: ...
@overload
def load(path: int) -> bytes: ...
def load(path):
    return path

load(|)
"""
    )
    assert ["path: str"] in [s["params"] for s in result.signatures]
    assert ["path: int"] in [s["params"] for s in result.signatures]


# "Sort by `(module_path, line)`." across modules
def test_signatures_sort_by_module_then_line(signatures):
    result = signatures(
        """
flag = True
if flag:
    from beta import run
else:
    from alpha import run

run(|)
""",
        files={"alpha.py": "def run(a):\n    pass\n", "beta.py": "def run(b):\n    pass\n"},
    )
    assert [s["params"] for s in result.signatures] == [["a"], ["b"]]


# "return the function's signature(s)" for a call written across several lines
def test_call_spanning_several_lines(signatures):
    result = signatures(
        """
def f(a, b):
    pass

f(
    1,
    |
)
"""
    )
    assert result.signature["name"] == "f"


# A method reached through a variable still finds its class.
def test_method_on_an_inferred_receiver(signatures):
    result = signatures(
        """
class Box:
    def put(self, item, count=1):
        pass

box = Box()
box.put(|)
"""
    )
    assert result.signature["params"] == ["item", "count=1"]


# A class call reports the constructor's parameters under the class name.
def test_calling_a_class_reports_its_constructor(signatures):
    result = signatures(
        """
class Box:
    def __init__(self, size):
        self.size = size

Box(|)
"""
    )
    assert result.signature["name"] == "Box"
    assert result.signature["params"] == ["size"]
