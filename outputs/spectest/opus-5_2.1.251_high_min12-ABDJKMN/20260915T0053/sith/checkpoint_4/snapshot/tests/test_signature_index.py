"""Spec section: `signatures` — parameter index detection."""
from conftest import CURSOR, sigs_at

C = CURSOR


def index_of(tmp_path, code):
    sigs = sigs_at(tmp_path, code)
    assert len(sigs) == 1, sigs
    return sigs[0]["index"]


DEF = "def f(a, b, c):\n    return a\n\n\n"


# --- Phrase: "index | int or null | 0-based index of the parameter the cursor
#     is currently on." (empty argument list -> first parameter)
def test_index_empty_call(tmp_path):
    assert index_of(tmp_path, DEF + "f(" + C + ")\n") == 0


# --- Phrase: "Positional arguments map left-to-right to declared positional
#     parameters." (second slot)
def test_index_second_positional(tmp_path):
    assert index_of(tmp_path, DEF + "f(1, " + C + ")\n") == 1


# --- Phrase: "Positional arguments map left-to-right ..." (third slot)
def test_index_third_positional(tmp_path):
    assert index_of(tmp_path, DEF + "f(1, 2, " + C + ")\n") == 2


# --- Phrase: "Positional arguments map left-to-right ..." (cursor inside a
#     half-typed first argument)
def test_index_partial_first_argument(tmp_path):
    assert index_of(tmp_path, DEF + "f(xy" + C + ")\n") == 0


# --- Phrase: "Keyword arguments map to the matching declared parameter when
#     present."
def test_index_keyword_argument(tmp_path):
    assert index_of(tmp_path, DEF + "f(c=" + C + ")\n") == 2


# --- Phrase: "Keyword arguments map to the matching declared parameter ..."
#     (after an earlier positional)
def test_index_keyword_after_positional(tmp_path):
    assert index_of(tmp_path, DEF + "f(1, b=" + C + ")\n") == 1


# --- Phrase: "Extra positional arguments map to `*args` when available"
def test_index_extra_positional_to_varargs(tmp_path):
    code = ("def g(a, *rest):\n    return a\n\n\n"
            "g(1, 2, 3, " + C + ")\n")
    assert index_of(tmp_path, code) == 1


# --- Phrase: "... otherwise `index` is `null`."
def test_index_extra_positional_without_varargs(tmp_path):
    assert index_of(tmp_path, DEF + "f(1, 2, 3, 4, " + C + ")\n") is None


# --- Phrase: "Unknown keyword arguments map to `**kwargs` when available"
def test_index_unknown_keyword_to_kwargs(tmp_path):
    code = ("def g(a, **opts):\n    return a\n\n\n"
            "g(zzz=" + C + ")\n")
    assert index_of(tmp_path, code) == 1


# --- Phrase: "... otherwise `index` is `null`." (unknown keyword)
def test_index_unknown_keyword_without_kwargs(tmp_path):
    assert index_of(tmp_path, DEF + "f(zzz=" + C + ")\n") is None


# --- Phrase: "`null` if the cursor is past all parameters" (no parameters at
#     all)
def test_index_no_parameters(tmp_path):
    code = "def g():\n    return 1\n\n\ng(" + C + ")\n"
    assert index_of(tmp_path, code) is None


# --- Phrase: keyword-only parameters are reachable by name.
def test_index_keyword_only(tmp_path):
    code = ("def g(a, *, flag=False):\n    return a\n\n\n"
            "g(1, flag=" + C + ")\n")
    assert index_of(tmp_path, code) == 1


# --- Phrase: a positional argument cannot land on a keyword-only parameter.
def test_index_positional_cannot_reach_keyword_only(tmp_path):
    code = ("def g(a, *, flag=False):\n    return a\n\n\n"
            "g(1, " + C + ")\n")
    assert index_of(tmp_path, code) is None


# --- Phrase: "*args" itself is a parameter representation with an index.
def test_index_on_varargs_slot(tmp_path):
    code = ("def g(a, *rest):\n    return a\n\n\n"
            "g(1, " + C + ")\n")
    assert index_of(tmp_path, code) == 1


# --- Phrase: positional-only parameters still count left-to-right.
def test_index_positional_only(tmp_path):
    code = ("def g(a, /, b):\n    return a\n\n\n"
            "g(1, " + C + ")\n")
    assert index_of(tmp_path, code) == 1


# --- Phrase: the params list never contains the bare `/` or `*` separators.
def test_params_have_no_separators(tmp_path):
    code = ("def g(a, /, b, *, c):\n    return a\n\n\n"
            "g(" + C + ")\n")
    assert sigs_at(tmp_path, code)[0]["params"] == ["a", "b", "c"]
