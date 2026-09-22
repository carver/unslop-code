"""The ``-j``/``--json`` export mode and its place in the output precedence."""

import json

from conftest import BOOKS, MIXED, PAGE

DUNE = {"title": "Dune"}
MISERABLES = {"title": "Les Miserables"}


# Spec: "`-j`, `--json`: JSON export mode for XML element results." -- the long
# form replaces the XML node output the same query produces on its own.
def test_json_flag_exports_element_results(run_xjq):
    result = run_xjq("--json", "//book/title", stdin=BOOKS)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [DUNE, MISERABLES]


# Spec: "`-j`, `--json`: JSON export mode ..." -- `-j` is the short form.
def test_json_flag_short_form(run_xjq):
    assert run_xjq("-j", "//book/title", stdin=BOOKS).stdout == run_xjq(
        "--json", "//book/title", stdin=BOOKS
    ).stdout


# Spec: "`-j`, `--json`: JSON export mode for XML element results." -- without
# the flag the same query still prints one serialized node.
def test_json_flag_is_opt_in(run_xjq):
    assert run_xjq("//book/title", stdin=BOOKS).stdout.rstrip("\n") == (
        "<title>Dune</title>"
    )


# Spec: "`-j`, `--json`: JSON export mode for XML element results." -- elements
# of a JSON-derived document export like any other.
def test_json_flag_on_json_derived_input(run_xjq):
    result = run_xjq("-j", "/root/*", stdin='{"a": "x", "b": "y"}')
    assert json.loads(result.stdout) == [{"a": "x"}, {"b": "y"}]


# Spec: "`-j`, `--json`: JSON export mode ..." -- a query that matches nothing
# stays silent rather than exporting an empty array (AMBIGUITIES T37).
def test_json_flag_without_matches_is_silent(run_xjq):
    result = run_xjq("-j", "//missing", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# Spec: "Export shape: JSON array of objects `{tag_name: immediate_text_content}`."
def test_export_shape_is_an_array_of_single_key_objects(run_xjq):
    exported = json.loads(run_xjq("-j", "//book/*", stdin=BOOKS).stdout)
    assert isinstance(exported, list)
    assert [sorted(entry) for entry in exported] == [["title"], ["author"]] * 2


# Spec: "Export shape: JSON array of objects `{tag_name: ...}`." -- the key is
# the element's own tag, so repeated tags repeat as separate objects.
def test_export_keys_are_tag_names(run_xjq):
    exported = json.loads(run_xjq("-j", "//title", stdin=BOOKS).stdout)
    assert exported == [DUNE, MISERABLES]


# Spec: "Export shape: JSON array of objects ..." -- a single match is still an
# array.
def test_single_match_exports_an_array(run_xjq):
    assert json.loads(run_xjq("-j", "//book[1]/title", stdin=BOOKS).stdout) == [DUNE]


# Spec: "Use immediate text only (exclude descendant text from child elements)."
def test_export_excludes_descendant_text(run_xjq):
    exported = json.loads(run_xjq("-j", "//book", stdin=BOOKS).stdout)
    assert exported == [{"book": ""}, {"book": ""}]


# Spec: "Use immediate text only (exclude descendant text from child elements)."
# -- the element's own text around a child is immediate text (AMBIGUITIES T33).
def test_export_keeps_the_elements_own_text_around_children(run_xjq):
    assert json.loads(run_xjq("-j", "//p", stdin=MIXED).stdout) == [{"p": "Hello !"}]


# Spec: "Use immediate text only ..." -- values are stripped and whitespace
# runs collapsed like every other text result (AMBIGUITIES T34).
def test_exported_text_is_stripped_and_collapsed(run_xjq):
    doc = "<r><t>  a\n\n  b\t\tc  </t></r>"
    assert json.loads(run_xjq("-j", "//t", stdin=doc).stdout) == [{"t": "a b c"}]


# Spec: "Default JSON formatting: 2-space indent."
def test_default_json_formatting_is_two_space_indent(run_xjq):
    result = run_xjq("-j", "//book[1]/title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == '[\n  {\n    "title": "Dune"\n  }\n]'


# Spec: "Default JSON formatting: 2-space indent." -- every nesting level adds
# two more spaces, across several exported elements.
def test_two_space_indent_across_several_elements(run_xjq):
    lines = run_xjq("-j", "//title", stdin=BOOKS).stdout.rstrip("\n").split("\n")
    assert lines[0] == "["
    assert lines[1] == "  {"
    assert lines[2] == '    "title": "Dune"'
    assert lines[3] == "  },"
    assert lines[-1] == "]"


# Spec: "With `--compact`, produce zero-indent JSON layout (no leading
# whitespace)." (AMBIGUITIES T36)
def test_compact_json_has_zero_indent(run_xjq):
    result = run_xjq("-j", "-c", "//book[1]/title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == '[\n{\n"title": "Dune"\n}\n]'


# Spec: "With `--compact`, produce zero-indent JSON layout (no leading
# whitespace)." -- no line of the payload starts with whitespace.
def test_compact_json_lines_have_no_leading_whitespace(run_xjq):
    result = run_xjq("--json", "--compact", "//title", stdin=BOOKS)
    lines = result.stdout.rstrip("\n").split("\n")
    assert all(line == line.lstrip() for line in lines)
    assert json.loads(result.stdout) == [DUNE, MISERABLES]


# Spec: "With `--first`, still return a JSON array containing one exported
# element."
def test_first_exports_a_one_element_array(run_xjq):
    assert json.loads(run_xjq("-j", "-f", "//title", stdin=BOOKS).stdout) == [DUNE]


# Spec: "With `--first`, still return a JSON array containing one exported
# element." -- the array keeps the default 2-space layout.
def test_first_keeps_the_json_layout(run_xjq):
    result = run_xjq("--json", "--first", "//title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == '[\n  {\n    "title": "Dune"\n  }\n]'


# Spec: "With `--first`, still return a JSON array ..." -- combined with
# `--compact` as well.
def test_first_and_compact_json_together(run_xjq):
    result = run_xjq("-j", "-f", "-c", "//title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == '[\n{\n"title": "Dune"\n}\n]'


# Spec: output precedence "1. `--text-all` ... 3. `--json`".
def test_text_all_wins_over_json(run_xjq):
    assert run_xjq("--text-all", "-j", "//book", stdin=BOOKS).stdout == (
        "Dune Frank Herbert\nLes Miserables Victor Hugo"
    )


# Spec: output precedence "2. `--text` ... 3. `--json`".
def test_text_wins_over_json(run_xjq):
    assert run_xjq("-t", "-j", "//title", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: output precedence "1. `--text-all` 2. `--text` 3. `--json`" -- with all
# three present the first one listed decides.
def test_full_precedence_order(run_xjq):
    result = run_xjq("--text-all", "--text", "--json", "//p", stdin=MIXED)
    assert result.stdout == "Hello World!"


# Spec: output precedence "3. `--json` 4. default auto-format behavior" -- the
# flag displaces the default node output but nothing else.
def test_json_wins_over_default_auto_format(run_xjq):
    assert run_xjq("-j", "//book[1]", stdin=BOOKS).stdout.startswith("[")
    assert run_xjq("//book[1]", stdin=BOOKS).stdout.startswith("<book")


# Spec: "`--json` has no effect when results are already auto-detected as text
# (e.g. text()/attribute outputs)." -- a `text()` query.
def test_json_has_no_effect_on_text_node_results(run_xjq):
    assert run_xjq("-j", "//title/text()", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "`--json` has no effect when results are already auto-detected as text
# (e.g. text()/attribute outputs)." -- an attribute query.
def test_json_has_no_effect_on_attribute_results(run_xjq):
    assert run_xjq("--json", "//book/@id", stdin=BOOKS).stdout == "b1\nb2"


# Spec: "`--json` has no effect when results are already auto-detected as text"
# -- scalar results are text results too.
def test_json_has_no_effect_on_scalar_results(run_xjq):
    assert run_xjq("-j", "count(//book)", stdin=BOOKS).stdout == "2"
    assert run_xjq("-j", "string(//title)", stdin=BOOKS).stdout == "Dune"


# Spec: "`--json` has no effect when results are already auto-detected as text"
# -- `--first` then still means the first text result.
def test_json_leaves_first_alone_on_text_results(run_xjq):
    assert run_xjq("-j", "-f", "//title/text()", stdin=BOOKS).stdout == "Dune"


# Spec: "In `--css` mode, `--json` has no effect and output follows the normal
# CSS rules for the query."
def test_json_has_no_effect_in_css_mode(run_xjq):
    plain = run_xjq("--css", "title", stdin=BOOKS).stdout
    assert run_xjq("--css", "-j", "title", stdin=BOOKS).stdout == plain
    assert plain.rstrip("\n") == "<title>Dune</title>"


# Spec: "In `--css` mode, `--json` has no effect ..." -- including for a
# `::text` selector, which follows the CSS text rules.
def test_json_has_no_effect_on_css_text_selectors(run_xjq):
    assert run_xjq("--css", "-j", "h1::text", stdin=PAGE).stdout == "First\nSecond"


# Spec: "In `--css` mode, `--json` has no effect ..." -- the other flags keep
# their CSS behaviour beside it.
def test_css_flags_still_apply_beside_json(run_xjq):
    assert run_xjq("--css", "-j", "-c", ".post", stdin=PAGE).stdout.startswith(
        '<div class="post" id="p1"><h1>'
    )
    assert run_xjq("--css", "-j", "-f", "--text-all", "h1", stdin=PAGE).stdout == (
        "First Post"
    )
