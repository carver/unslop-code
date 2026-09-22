"""Tests for the `signatures` subcommand, one section per spec phrase."""

import json

import pytest

from conftest import (make_project, prun, psigs, run_raw, sigs, sigs_raw,
                      split_cursor, write)


def params_of(signatures):
    return [s["params"] for s in signatures]


# =====================================================================
# CLI surface
# =====================================================================

# Spec: "python sith.py signatures <file> <line> <col> [--project <dir>]"
def test_cli_accepts_signatures_subcommand(tmp_path):
    r = sigs_raw(tmp_path, "def f(a):\n    pass\nf(<|>)\n")
    assert r.returncode == 0, r.stderr
    assert "signatures" in json.loads(r.stdout)


# Spec: "python sith.py signatures <file> <line> <col> [--project <dir>]"
# Context: the payload is a JSON array under the "signatures" key (T53).
def test_signatures_payload_is_an_array(tmp_path):
    r = sigs_raw(tmp_path, "def f(a):\n    pass\nf(<|>)\n")
    assert isinstance(json.loads(r.stdout)["signatures"], list)


# Spec: "[--project <dir>]"
def test_signatures_accepts_project_flag(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/lib.py": "def helper(a, b):\n    pass\n",
             "pkg/main.py": "from pkg.lib import helper\nhelper(<|>)\n"}
    out = psigs(tmp_path, files, project=True)
    assert [s["name"] for s in out] == ["helper"]


# Spec: the output is compact JSON, as for the other subcommands.
def test_signatures_output_is_compact_and_newline_terminated(tmp_path):
    r = sigs_raw(tmp_path, "def f(a):\n    pass\nf(<|>)\n")
    assert r.stdout.endswith("\n")
    assert ", " not in r.stdout and '": ' not in r.stdout


# =====================================================================
# "When the cursor is inside a function call's argument list, return the
#  function's signature(s)"
# =====================================================================

# Spec: "When the cursor is inside a function call's argument list, return the function's signature(s)"
def test_cursor_in_argument_list_returns_the_signature(tmp_path):
    out = sigs(tmp_path, "def greet(name):\n    pass\ngreet(<|>)\n")
    assert len(out) == 1
    assert out[0]["name"] == "greet"


# Spec: "| `name` | string | Function or class name. |"
def test_name_field_is_the_function_name(tmp_path):
    out = sigs(tmp_path, "def compute(a):\n    pass\ncompute(<|>)\n")
    assert out[0]["name"] == "compute"


# Spec: "| `name` | string | Function or class name. |"
# Context: a constructor call reports the class name (T56).
def test_name_field_of_a_class_is_the_class_name(tmp_path):
    src = ("class Widget:\n"
           "    def __init__(self, size):\n"
           "        pass\n"
           "Widget(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["name"] == "Widget"


# Spec: "If the cursor is not inside a call's parentheses, return an empty
#        signatures array (exit 0)."
def test_cursor_outside_any_call_returns_empty(tmp_path):
    r = sigs_raw(tmp_path, "def f(a):\n    pass\nx = <|>1\n")
    assert r.returncode == 0
    assert json.loads(r.stdout)["signatures"] == []


# Spec: "If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0)."
# Context: on the callee name itself, before the paren (T58).
def test_cursor_on_the_callee_name_returns_empty(tmp_path):
    assert sigs(tmp_path, "def f(a):\n    pass\nf<|>(1)\n") == []


# Spec: "If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0)."
# Context: after the closing parenthesis the call is complete (T58).
def test_cursor_after_the_closing_paren_returns_empty(tmp_path):
    assert sigs(tmp_path, "def f(a):\n    pass\nf(1)<|>\n") == []


# Spec: "If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0)."
# Context: a list display is not a call (T58).
def test_cursor_inside_a_list_display_returns_empty(tmp_path):
    assert sigs(tmp_path, "x = [1, <|>]\n") == []


# Spec: "the function's signature(s)". Context: an unresolvable callee has none.
def test_unknown_callee_returns_empty(tmp_path):
    assert sigs(tmp_path, "mystery(<|>)\n") == []


# Spec: "When the cursor is inside a function call's argument list"
# Context: the innermost open call wins (T58).
def test_nested_call_reports_the_inner_callee(tmp_path):
    src = ("def outer(a):\n    pass\n"
           "def inner(b):\n    pass\n"
           "outer(inner(<|>))\n")
    out = sigs(tmp_path, src)
    assert [s["name"] for s in out] == ["inner"]


# Spec: "When the cursor is inside a function call's argument list"
# Context: back in the outer argument list after the inner call closed (T58).
def test_after_nested_call_reports_the_outer_callee(tmp_path):
    src = ("def outer(a, b):\n    pass\n"
           "def inner():\n    pass\n"
           "outer(inner(), <|>)\n")
    out = sigs(tmp_path, src)
    assert [s["name"] for s in out] == ["outer"]


# Spec: "When the cursor is inside a function call's argument list"
# Context: a call spanning several lines (T58).
def test_multiline_call(tmp_path):
    src = ("def f(a, b):\n    pass\n"
           "f(\n"
           "    1,\n"
           "    <|>\n"
           ")\n")
    out = sigs(tmp_path, src)
    assert out[0]["name"] == "f" and out[0]["index"] == 1


# Spec: "When the cursor is inside a function call's argument list"
# Context: a method call on an instance.
def test_method_call_on_an_instance(tmp_path):
    src = ("class Thing:\n"
           "    def run(self, speed):\n"
           "        pass\n"
           "t = Thing()\n"
           "t.run(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["name"] == "run"


# =====================================================================
# `params` rendering
# =====================================================================

# Spec: '`"name"` for bare parameters'
def test_bare_parameters(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a", "b"]


# Spec: '`"name: type"` for annotated parameters (one space after colon)'
def test_annotated_parameter(tmp_path):
    out = sigs(tmp_path, "def f(a: int):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a: int"]


# Spec: '`"name=default"` for parameters with defaults (no spaces around `=`)'
def test_parameter_with_default(tmp_path):
    out = sigs(tmp_path, "def f(a=1):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a=1"]


# Spec: '`"name: type=default"` for both (no spaces around `=` even with annotation)'
def test_annotated_parameter_with_default(tmp_path):
    out = sigs(tmp_path, "def f(a: int = 1):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a: int=1"]


# Spec: 'Special forms: `"*args"`'
def test_star_args(tmp_path):
    out = sigs(tmp_path, "def f(*args):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["*args"]


# Spec: 'Special forms: ... `"**kwargs"`'
def test_star_star_kwargs(tmp_path):
    out = sigs(tmp_path, "def f(**kwargs):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["**kwargs"]


# Spec: 'Special forms: ... `"*args: type"`'
def test_annotated_star_args(tmp_path):
    out = sigs(tmp_path, "def f(*args: int):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["*args: int"]


# Spec: 'Special forms: ... `"**kwargs: type"`'
def test_annotated_star_star_kwargs(tmp_path):
    out = sigs(tmp_path, "def f(**kwargs: str):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["**kwargs: str"]


# Spec: "Parameter representations."
# Context: a string default keeps its literal form.
def test_string_default(tmp_path):
    out = sigs(tmp_path, "def f(a='x'):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a='x'"]


# Spec: "Parameter representations."
# Context: a dotted annotation is rendered as written.
def test_dotted_annotation(tmp_path):
    out = sigs(tmp_path, "import os\ndef f(p: os.PathLike):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["p: os.PathLike"]


# Spec: "Parameter representations."
# Context: the whole mixture, in declaration order.
def test_mixed_parameter_forms(tmp_path):
    src = ("def f(a, b: int, c=3, d: str='x', *args: float, e=5, **kw: bool):\n"
           "    pass\n"
           "f(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["params"] == ["a", "b: int", "c=3", "d: str='x'",
                                "*args: float", "e=5", "**kw: bool"]


# Spec: "Parameter representations." Context: no parameters at all.
def test_no_parameters(tmp_path):
    out = sigs(tmp_path, "def f():\n    pass\nf(<|>)\n")
    assert out[0]["params"] == []


# Spec: "Parameter representations."
# Context: `/` and `*` markers are not parameters (T55).
def test_positional_only_and_keyword_only_markers_are_dropped(tmp_path):
    out = sigs(tmp_path, "def f(a, /, b, *, c):\n    pass\nf(<|>)\n")
    assert out[0]["params"] == ["a", "b", "c"]


# Spec: "The `self` parameter is excluded for methods." (T54)
def test_self_is_excluded_from_params(tmp_path):
    src = ("class Thing:\n"
           "    def run(self, speed, force=1):\n"
           "        pass\n"
           "Thing().run(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["params"] == ["speed", "force=1"]


# Spec: "The `self` parameter is excluded for methods." (T54)
# Context: `cls` of a classmethod is bound the same way.
def test_cls_is_excluded_from_a_classmethod(tmp_path):
    src = ("class Thing:\n"
           "    @classmethod\n"
           "    def make(cls, size):\n"
           "        pass\n"
           "Thing.make(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["params"] == ["size"]


# Spec: "The `self` parameter is excluded for methods." (T54)
# Context: a staticmethod has no bound first parameter.
def test_staticmethod_keeps_all_parameters(tmp_path):
    src = ("class Thing:\n"
           "    @staticmethod\n"
           "    def helper(a, b):\n"
           "        pass\n"
           "Thing.helper(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["params"] == ["a", "b"]


# Spec: "| `name` | string | Function or class name. |" (T56)
# Context: a constructor's parameters come from `__init__`, minus `self`.
def test_class_params_come_from_init(tmp_path):
    src = ("class Widget:\n"
           "    def __init__(self, size: int, color='red'):\n"
           "        pass\n"
           "Widget(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["params"] == ["size: int", "color='red'"]


# =====================================================================
# `description`
# =====================================================================

# Spec: '`"def name(params)"` for functions without return annotation'
def test_description_without_return_annotation(tmp_path):
    out = sigs(tmp_path, "def f(a, b=2):\n    pass\nf(<|>)\n")
    assert out[0]["description"] == "def f(a, b=2)"


# Spec: '`"def name(params) -> ReturnType"` when the function has a return type annotation'
def test_description_with_return_annotation(tmp_path):
    out = sigs(tmp_path, "def f(a: int) -> str:\n    pass\nf(<|>)\n")
    assert out[0]["description"] == "def f(a: int) -> str"


# Spec: '`"def name(params)"`' Context: no parameters.
def test_description_without_parameters(tmp_path):
    out = sigs(tmp_path, "def f():\n    pass\nf(<|>)\n")
    assert out[0]["description"] == "def f()"


# Spec: "The `self` parameter is excluded for methods."
def test_description_of_a_method_excludes_self(tmp_path):
    src = ("class Thing:\n"
           "    def run(self, speed) -> bool:\n"
           "        pass\n"
           "Thing().run(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["description"] == "def run(speed) -> bool"


# Spec: description is built from the same `params` list.
def test_description_is_params_joined_with_comma_space(tmp_path):
    out = sigs(tmp_path, "def f(a, b, c):\n    pass\nf(<|>)\n")
    assert out[0]["description"] == "def f(%s)" % ", ".join(out[0]["params"])


# Spec: "| `name` | string | Function or class name. |" (T56)
def test_description_of_a_class(tmp_path):
    src = ("class Widget:\n"
           "    def __init__(self, size):\n"
           "        pass\n"
           "Widget(<|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["description"] == "def Widget(size)"


# =====================================================================
# `docstring`
# =====================================================================

# Spec: "| `docstring` | string | Function's docstring, or empty string. |"
def test_docstring_is_returned(tmp_path):
    src = ('def f(a):\n'
           '    """Do the thing."""\n'
           '    pass\n'
           'f(<|>)\n')
    out = sigs(tmp_path, src)
    assert out[0]["docstring"] == "Do the thing."


# Spec: "| `docstring` | string | Function's docstring, or empty string. |"
def test_missing_docstring_is_empty_string(tmp_path):
    out = sigs(tmp_path, "def f(a):\n    pass\nf(<|>)\n")
    assert out[0]["docstring"] == ""


# Spec: "| `docstring` | string | Function's docstring, or empty string. |"
# Context: a class's own docstring describes its constructor (T56).
def test_class_docstring(tmp_path):
    src = ('class Widget:\n'
           '    """A widget."""\n'
           '    def __init__(self, size):\n'
           '        pass\n'
           'Widget(<|>)\n')
    out = sigs(tmp_path, src)
    assert out[0]["docstring"] == "A widget."


# =====================================================================
# `index` -- parameter index detection
# =====================================================================

# Spec: "| `index` | int or null | 0-based index of the parameter the cursor is currently on. |"
def test_index_of_the_first_argument(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf(<|>)\n")
    assert out[0]["index"] == 0


# Spec: "Positional arguments map left-to-right to declared positional parameters."
def test_index_after_one_positional_argument(tmp_path):
    out = sigs(tmp_path, "def f(a, b, c):\n    pass\nf(1, <|>)\n")
    assert out[0]["index"] == 1


# Spec: "Positional arguments map left-to-right to declared positional parameters."
def test_index_after_two_positional_arguments(tmp_path):
    out = sigs(tmp_path, "def f(a, b, c):\n    pass\nf(1, 2, <|>)\n")
    assert out[0]["index"] == 2


# Spec: "Positional arguments map left-to-right to declared positional parameters."
# Context: the cursor part-way through typing an argument stays on it.
def test_index_while_typing_an_argument(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf(12<|>)\n")
    assert out[0]["index"] == 0


# Spec: "Keyword arguments map to the matching declared parameter when present."
def test_index_of_a_keyword_argument(tmp_path):
    out = sigs(tmp_path, "def f(a, b, c):\n    pass\nf(c=<|>)\n")
    assert out[0]["index"] == 2


# Spec: "Keyword arguments map to the matching declared parameter when present."
# Context: a keyword argument does not consume a positional slot.
def test_keyword_then_positional_is_unchanged(tmp_path):
    out = sigs(tmp_path, "def f(a, b, c):\n    pass\nf(c=3, <|>)\n")
    assert out[0]["index"] == 0


# Spec: "Keyword arguments map to the matching declared parameter when present."
# Context: a keyword-only parameter is reachable only by keyword.
def test_index_of_a_keyword_only_parameter(tmp_path):
    out = sigs(tmp_path, "def f(a, *, mode):\n    pass\nf(1, mode=<|>)\n")
    assert out[0]["index"] == 1


# Spec: "Extra positional arguments map to `*args` when available"
def test_extra_positional_maps_to_star_args(tmp_path):
    out = sigs(tmp_path, "def f(a, *rest):\n    pass\nf(1, 2, <|>)\n")
    assert out[0]["index"] == 1


# Spec: "Extra positional arguments map to `*args` when available, otherwise `index` is `null`."
def test_extra_positional_without_star_args_is_null(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf(1, 2, <|>)\n")
    assert out[0]["index"] is None


# Spec: "Unknown keyword arguments map to `**kwargs` when available"
def test_unknown_keyword_maps_to_kwargs(tmp_path):
    out = sigs(tmp_path, "def f(a, **kw):\n    pass\nf(zzz=<|>)\n")
    assert out[0]["index"] == 1


# Spec: "Unknown keyword arguments map to `**kwargs` when available, otherwise `index` is `null`."
def test_unknown_keyword_without_kwargs_is_null(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf(zzz=<|>)\n")
    assert out[0]["index"] is None


# Spec: "`null` if the cursor is past all parameters"
def test_index_is_null_when_the_function_takes_nothing(tmp_path):
    out = sigs(tmp_path, "def f():\n    pass\nf(<|>)\n")
    assert out[0]["index"] is None


# Spec: "`null` ... or in an ambiguous position." Context: a `*` unpacking (T57).
def test_index_is_null_for_a_star_unpacking(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nrest = []\nf(*rest<|>)\n")
    assert out[0]["index"] is None


# Spec: "`null` ... or in an ambiguous position." Context: a `**` unpacking (T57).
def test_index_is_null_for_a_double_star_unpacking(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nkw = {}\nf(**kw<|>)\n")
    assert out[0]["index"] is None


# Spec: "`index` follows Python-style call binding at the cursor position"
# Context: `self` is excluded, so the first argument of a bound call is index 0 (T54).
def test_index_of_a_bound_method_call_skips_self(tmp_path):
    src = ("class Thing:\n"
           "    def run(self, speed, force):\n"
           "        pass\n"
           "Thing().run(1, <|>)\n")
    out = sigs(tmp_path, src)
    assert out[0]["index"] == 1


# Spec: "`index` follows Python-style call binding at the cursor position"
# Context: commas nested inside another bracket do not separate arguments (T58).
def test_nested_bracket_commas_do_not_advance_the_index(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nf([1, 2, 3]<|>)\n")
    assert out[0]["index"] == 0


# Spec: "`index` follows Python-style call binding at the cursor position"
# Context: a comma inside a string literal is not a separator.
def test_comma_inside_a_string_does_not_advance_the_index(tmp_path):
    out = sigs(tmp_path, 'def f(a, b):\n    pass\nf("x, y"<|>)\n')
    assert out[0]["index"] == 0


# Spec: "`index` follows Python-style call binding at the cursor position"
# Context: `==` is not a keyword argument (T72).
def test_comparison_is_not_a_keyword_argument(tmp_path):
    out = sigs(tmp_path, "def f(a, b):\n    pass\nx = 1\nf(x == 2, <|>)\n")
    assert out[0]["index"] == 1


# Spec: "Keyword arguments map to the matching declared parameter when present."
# Context: a bare prefix is not yet a keyword argument (T72).
def test_bare_prefix_is_still_positional(tmp_path):
    out = sigs(tmp_path, "def f(alpha, beta):\n    pass\nf(bet<|>)\n")
    assert out[0]["index"] == 0


# =====================================================================
# Multiple signatures
# =====================================================================

# Spec: "Multiple signatures are returned when the callable has overloads"
def test_overloads_produce_multiple_signatures(tmp_path):
    src = ("from typing import overload\n"
           "@overload\n"
           "def f(a: int) -> int: ...\n"
           "@overload\n"
           "def f(a: str) -> str: ...\n"
           "def f(a):\n"
           "    return a\n"
           "f(<|>)\n")
    out = sigs(tmp_path, src)
    assert [s["params"] for s in out] == [["a: int"], ["a: str"]]


# Spec: "or when the name resolves to multiple possible functions"
def test_branch_defined_functions_produce_multiple_signatures(tmp_path):
    src = ("flag = True\n"
           "if flag:\n"
           "    def f(a):\n"
           "        pass\n"
           "else:\n"
           "    def f(b, c):\n"
           "        pass\n"
           "f(<|>)\n")
    out = sigs(tmp_path, src)
    assert [s["params"] for s in out] == [["a"], ["b", "c"]]


# Spec: "Sort by `(module_path, line)`."
def test_multiple_signatures_sorted_by_line(tmp_path):
    src = ("flag = True\n"
           "if flag:\n"
           "    def f(z):\n"
           "        pass\n"
           "else:\n"
           "    def f(a):\n"
           "        pass\n"
           "f(<|>)\n")
    out = sigs(tmp_path, src)
    assert [s["params"] for s in out] == [["z"], ["a"]]


# Spec: "Sort by `(module_path, line)`."
# Context: across modules the path orders first.
def test_multiple_signatures_sorted_by_module_path(tmp_path):
    files = {
        "zeta.py": "def f(z):\n    pass\n",
        "alpha.py": "def f(a):\n    pass\n",
        "main.py": ("import alpha\n"
                    "import zeta\n"
                    "flag = True\n"
                    "if flag:\n"
                    "    g = alpha.f\n"
                    "else:\n"
                    "    g = zeta.f\n"
                    "g(<|>)\n"),
    }
    out = psigs(tmp_path, files, project=True)
    assert [s["params"] for s in out] == [["a"], ["z"]]


# =====================================================================
# Dynamic parameter inference (T69)
# =====================================================================

# Spec: "the tool can optionally infer parameter types by finding call sites.
#        This is enabled by default and affects `infer` and `signatures`."
def test_call_site_inference_resolves_a_method_signature(tmp_path):
    src = ("class Widget:\n"
           "    def paint(self, color):\n"
           "        pass\n"
           "def outer(thing):\n"
           "    thing.paint(<|>)\n"
           "outer(Widget())\n")
    out = sigs(tmp_path, src)
    assert [s["name"] for s in out] == ["paint"]
    assert out[0]["params"] == ["color"]


# Spec: "Do not search other files for call sites."
def test_call_sites_in_other_files_are_ignored(tmp_path):
    files = {
        "lib.py": ("class Widget:\n"
                   "    def paint(self, color):\n"
                   "        pass\n"
                   "def outer(thing):\n"
                   "    thing.paint(<|>)\n"),
        "main.py": ("from lib import Widget, outer\n"
                    "outer(Widget())\n"),
    }
    assert psigs(tmp_path, files, project=True) == []


# Spec: "When a function has no type annotations and no stub"
# Context: an annotation wins over any call site.
def test_annotation_beats_call_site_inference(tmp_path):
    src = ("class A:\n"
           "    def go(self, x):\n"
           "        pass\n"
           "class B:\n"
           "    def go(self, y, z):\n"
           "        pass\n"
           "def outer(thing: A):\n"
           "    thing.go(<|>)\n"
           "outer(B())\n")
    out = sigs(tmp_path, src)
    assert [s["params"] for s in out] == [["x"]]


# Spec: "If the cursor is not inside a call's parentheses, return an empty
#        signatures array (exit 0)."
# Context: a `def` header's parameter list is a declaration, not a call (T58).
def test_cursor_in_a_def_header_returns_empty(tmp_path):
    assert sigs(tmp_path, "def f(a<|>):\n    pass\n") == []


# Spec: "If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0)."
# Context: a `class` header's base list is a declaration, not a call (T58).
def test_cursor_in_a_class_header_returns_empty(tmp_path):
    src = ("class Base:\n"
           "    def __init__(self, q):\n"
           "        pass\n"
           "class Kid(<|>Base):\n"
           "    pass\n")
    assert sigs(tmp_path, src) == []


# Spec: "| `name` | string | Function or class name. |" (T56)
# Context: a class without its own `__init__` uses the inherited one.
def test_inherited_init_is_used(tmp_path):
    src = ("class Base:\n"
           "    def __init__(self, q):\n"
           "        pass\n"
           "class Kid(Base):\n"
           "    pass\n"
           "Kid(<|>)\n")
    out = sigs(tmp_path, src)
    assert (out[0]["name"], out[0]["params"]) == ("Kid", ["q"])


# Spec: "| `name` | string | Function or class name. |" (T56)
# Context: a class with no constructor anywhere has no parameters.
def test_class_without_init(tmp_path):
    out = sigs(tmp_path, "class Bare:\n    pass\nBare(<|>)\n")
    assert (out[0]["params"], out[0]["index"]) == ([], None)


# Spec: "When the cursor is inside a function call's argument list"
# Context: a callable from the target runtime still reports a signature.
def test_runtime_callable_signature(tmp_path):
    out = sigs(tmp_path, "import os\nos.path.join(<|>)\n")
    assert out and out[0]["name"] == "join"
    assert out[0]["index"] == 0
