"""`signatures`: which parameter the cursor is currently on."""


# "| `index` | int or null | 0-based index of the parameter the cursor is
#  currently on. |"
def test_first_parameter_is_index_zero(signatures):
    result = signatures("def f(a, b):\n    pass\n\nf(|)\n")
    assert result.signature["index"] == 0


# "Positional arguments map left-to-right to declared positional parameters."
def test_second_positional_argument(signatures):
    result = signatures("def f(a, b, c):\n    pass\n\nf(1, |)\n")
    assert result.signature["index"] == 1


def test_third_positional_argument(signatures):
    result = signatures("def f(a, b, c):\n    pass\n\nf(1, 2, |)\n")
    assert result.signature["index"] == 2


# The cursor inside a half-typed argument still belongs to that argument.
def test_cursor_inside_an_argument(signatures):
    result = signatures("def f(a, b):\n    pass\n\nf(1, val|)\n")
    assert result.signature["index"] == 1


# "Keyword arguments map to the matching declared parameter when present."
def test_keyword_argument_selects_its_parameter(signatures):
    result = signatures("def f(a, b, c):\n    pass\n\nf(c=|)\n")
    assert result.signature["index"] == 2


def test_keyword_argument_after_a_positional_one(signatures):
    result = signatures("def f(a, b, c):\n    pass\n\nf(1, c=|)\n")
    assert result.signature["index"] == 2


# "Extra positional arguments map to `*args` when available"
def test_extra_positional_goes_to_star_args(signatures):
    result = signatures("def f(a, *rest):\n    pass\n\nf(1, 2, |)\n")
    assert result.signature["index"] == 1


# "otherwise `index` is `null`."
def test_extra_positional_without_star_args_is_null(signatures):
    result = signatures("def f(a, b):\n    pass\n\nf(1, 2, 3, |)\n")
    assert result.signature["index"] is None


# "Unknown keyword arguments map to `**kwargs` when available"
def test_unknown_keyword_goes_to_double_star(signatures):
    result = signatures("def f(a, **extra):\n    pass\n\nf(other=|)\n")
    assert result.signature["index"] == 1


# "otherwise `index` is `null`."
def test_unknown_keyword_without_kwargs_is_null(signatures):
    result = signatures("def f(a, b):\n    pass\n\nf(other=|)\n")
    assert result.signature["index"] is None


# A keyword-only parameter is still reached by its name; the bare `*` marker
# is not a parameter of its own.
def test_keyword_only_parameter(signatures):
    result = signatures("def f(a, *, flag=False):\n    pass\n\nf(1, flag=|)\n")
    assert result.signature["params"] == ["a", "flag=False"]
    assert result.signature["index"] == 1


# A function taking nothing has no parameter to sit on.
def test_call_with_no_parameters_at_all(signatures):
    result = signatures("def f():\n    pass\n\nf(|)\n")
    assert result.signature["index"] is None


# The index is counted per signature, so `self` does not shift it.
def test_index_skips_self_on_a_method(signatures):
    result = signatures(
        """
class Box:
    def put(self, item, count):
        pass

Box().put(1, |)
"""
    )
    assert result.signature["index"] == 1


# A nested call takes the cursor; the outer call is not the one being typed.
def test_nested_call_wins(signatures):
    result = signatures(
        """
def outer(a, b):
    pass

def inner(x, y):
    pass

outer(1, inner(1, |))
"""
    )
    assert result.signature["name"] == "inner"
    assert result.signature["index"] == 1


# A comma inside a nested display does not advance the outer argument.
def test_comma_inside_a_nested_list(signatures):
    result = signatures("def f(a, b):\n    pass\n\nf([1, 2|])\n")
    assert result.signature["index"] == 0


# Each signature gets the index the cursor means for it.
def test_index_differs_between_signatures(signatures):
    result = signatures(
        """
flag = True
if flag:
    def handle(first):
        pass
else:
    def handle(second, third):
        pass

handle(1, |)
"""
    )
    assert [s["index"] for s in result.signatures] == [None, 1]
