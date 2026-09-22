"""Spec section: XPath Union.

`|` joins location paths in XPath mode, and the text flags behave differently
across a union than they do over a single path.
"""

import json

from conftest import CSS_DOC, UNION_DOC


# Phrase: "Support XPath `|` union in XPath mode."
def test_union_query_matches_both_sub_paths(xjq):
    result = xjq("-j", "//h1 | //footer", stdin=UNION_DOC)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"h1": "Main Title"}, {"footer": "Bye"}]


# Phrase: "Support XPath `|` union in XPath mode."
# Without text flags a union is an ordinary node set, so the default
# first-node XML output applies.
def test_union_node_output_serializes_the_first_match(xjq):
    assert xjq("//h1 | //footer", stdin=UNION_DOC).stdout == "<h1>Main Title</h1>\n"


# Phrase: "`--text` and `--text-all` apply across union queries."
def test_text_applies_to_every_union_match(xjq):
    assert xjq("--text", "//h1 | //footer", stdin=UNION_DOC).stdout == "Main Title\nBye\n"


# Phrase: "For XPath union queries with active `--text-all`, concatenate
#          descendant text across all union matches into one normalized
#          output string."
def test_text_all_concatenates_union_matches_into_one_line(xjq):
    result = xjq("--text-all", "//h1 | //footer", stdin=UNION_DOC)
    assert result.returncode == 0
    assert result.stdout == "Main Title Bye\n"


# Phrase: "... concatenate descendant text across all union matches into one
#          normalized output string." -- descendant text of a nested match is
#          normalized before it joins the rest.
def test_union_text_all_normalizes_nested_descendant_text(xjq):
    assert xjq("--text-all", "//section | //footer", stdin=UNION_DOC).stdout == (
        "First para Bye\n"
    )


# Phrase: "... across all union matches ..." -- a union of three paths.
def test_union_text_all_spans_every_sub_path(xjq):
    assert xjq("--text-all", "//h1 | //section | //footer", stdin=UNION_DOC).stdout == (
        "Main Title First para Bye\n"
    )


# Phrase: "If `--first` is also active with union + `--text-all`, only the
#          first matched union node contributes to the output."
def test_first_limits_union_text_all_to_the_first_node(xjq):
    assert xjq("--first", "--text-all", "//h1 | //footer", stdin=UNION_DOC).stdout == (
        "Main Title\n"
    )


# Phrase: "... only the first matched union node contributes to the output."
# The whole of that node contributes, not just its first text node.
def test_first_union_node_contributes_all_of_its_descendant_text(xjq):
    assert xjq("-f", "--text-all", "//section | //footer", stdin=UNION_DOC).stdout == (
        "First para\n"
    )


# Phrase: "... only the first matched union node ..." -- the union is a node
# set in document order, so which sub-path is written first does not pick the
# winner (T44).
def test_first_union_node_is_the_first_in_document_order(xjq):
    written_last = xjq("-f", "--text-all", "//footer | //h1", stdin=UNION_DOC)
    assert written_last.stdout == "Main Title\n"


# Phrase: "If any union sub-path already performs text extraction, text flags
#          are treated as no-op query modifiers."
def test_text_flags_are_no_ops_when_a_sub_path_extracts_text(xjq):
    plain = xjq("//h1/text() | //footer/text()", stdin=UNION_DOC).stdout
    assert xjq("--text", "//h1/text() | //footer/text()", stdin=UNION_DOC).stdout == plain
    assert xjq("--text-all", "//h1/text() | //footer/text()", stdin=UNION_DOC).stdout == plain
    assert plain == "Main Title\nBye\n"


# Phrase: "If any union sub-path already performs text extraction ..."
# One extracting sub-path is enough to disarm the flags for the whole union.
def test_one_extracting_sub_path_disarms_the_flags(xjq):
    result = xjq("--text-all", "//h1/text() | //footer", stdin=UNION_DOC)
    assert result.returncode == 0
    assert result.stdout == "Main Title\nBye\n"


# Phrase: "Support XPath `|` union" -- a `|` inside a string literal is part of
# that literal, not a union operator, so `--text-all` stays per-element (T41).
def test_pipe_inside_a_predicate_literal_is_not_a_union(xjq):
    result = xjq("--text-all", '//note[text()="a|b"]', stdin=UNION_DOC)
    assert result.stdout == "a|b\na|b\n"


# Phrase: "In CSS mode, pass `|` through as CSS query text (no XPath union
#          semantics). If the CSS engine rejects the selector, report a CSS
#          selector error on stderr with exit code `1`."
def test_css_mode_rejects_a_union_style_selector(xjq):
    result = xjq("--css", "h1 | footer", stdin=UNION_DOC)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "selector" in result.stderr.lower() or "css" in result.stderr.lower()


# Phrase: "In CSS mode, pass `|` through as CSS query text (no XPath union
#          semantics)." -- a CSS selector list is not a union either, so
#          `--text-all` keeps its per-element line output there.
def test_css_selector_lists_do_not_gain_union_semantics(xjq):
    result = xjq("--css", "--text-all", "p, span", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stdout == "Hello\nbold\nworld\nSecond\nSpan text\n"
