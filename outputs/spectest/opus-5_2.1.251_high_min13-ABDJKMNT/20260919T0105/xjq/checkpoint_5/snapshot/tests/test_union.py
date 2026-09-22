"""XPath `|` union queries and what the text flags do with them.

Spec section: "## XPath Union".
"""

import json

PAIR = "<r><a>Hello</a><b>World</b></r>"
NESTED = "<r><div>Hello <b>World</b>!</div><p>Bye</p></r>"
INDENTED = "<r>\n  <a>one</a>\n  <b>two</b>\n</r>"


# Spec: "Support XPath `|` union in XPath mode."
# Context: both sides of the union contribute to the result set.
def test_union_matches_both_sub_paths(run_xjq):
    result = run_xjq("//a/text()|//b/text()", stdin=PAIR)
    assert result.returncode == 0
    assert result.lines == ["Hello", "World"]


# Spec: "Support XPath `|` union in XPath mode."
# Context: the matches come back in document order whichever way round the
# union is written, so element output prints the first node of the document.
# See AMBIGUITIES.md T49.
def test_union_results_are_in_document_order(run_xjq):
    assert run_xjq("//b|//a", stdin=PAIR).stdout.strip() == "<a>Hello</a>"
    assert run_xjq("//b/text()|//a/text()", stdin=PAIR).lines == ["Hello", "World"]


# Spec: "Support XPath `|` union in XPath mode."
# Context: a node matched by both sub-paths is one match, not two.
def test_union_does_not_repeat_a_shared_match(run_xjq):
    assert run_xjq("//a/text()|//a/text()", stdin=PAIR).lines == ["Hello"]


# Spec: "`--text` and `--text-all` apply across union queries."
# Context: `--text` extracts the direct text of every match on either side.
def test_text_flag_applies_across_the_union(run_xjq):
    assert run_xjq("-t", "//a|//b", stdin=PAIR).lines == ["Hello", "World"]


# Spec: "For XPath union queries with active `--text-all`, concatenate
#        descendant text across all union matches into one normalized output
#        string."
# Context: the matches share one line instead of taking one line each.
# See AMBIGUITIES.md T41.
def test_text_all_concatenates_union_matches(run_xjq):
    result = run_xjq("--text-all", "//a|//b", stdin=PAIR)
    assert result.returncode == 0
    assert result.stdout == "Hello World\n"


# Spec: "... concatenate descendant text across all union matches into one
#        normalized output string."
# Context: within a match the descendant text runs together as the document
# wrote it, so mixed content keeps its own spacing.
def test_union_concatenation_keeps_mixed_content_spacing(run_xjq):
    assert run_xjq("--text-all", "//div|//p", stdin=NESTED).stdout == "Hello World! Bye\n"


# Spec: "... into one normalized output string."
# Context: the layout whitespace of an indented document collapses away
# instead of turning into blank lines.
def test_union_concatenation_normalizes_whitespace(run_xjq):
    assert run_xjq("--text-all", "//r|//a", stdin=INDENTED).stdout == "one two one\n"


# Spec: "`--text` and `--text-all` apply across union queries."
# Context: the concatenation belongs to unions only; a single path still
# prints one line per text node.
def test_text_all_without_a_union_is_unchanged(run_xjq):
    assert run_xjq("--text-all", "//div", stdin=NESTED).lines == ["Hello", "World", "!"]


# Spec: "Support XPath `|` union in XPath mode."
# Context: a `|` inside a predicate is a union of that predicate's node sets,
# not a union of the query, so the text output is per text node.
def test_pipe_inside_a_predicate_is_not_a_query_union(run_xjq):
    result = run_xjq("--text-all", "//*[self::a|self::b]", stdin=PAIR)
    assert result.lines == ["Hello", "World"]


# Spec: "Support XPath `|` union in XPath mode."
# Context: a `|` inside a string literal is data, not a union operator.
def test_pipe_inside_a_string_literal_is_not_a_union(run_xjq):
    doc = "<r><a id='x|y'>Hello</a></r>"
    assert run_xjq("--text-all", "//a[@id='x|y']", stdin=doc).lines == ["Hello"]


# Spec: "If `--first` is also active with union + `--text-all`, only the first
#        matched union node contributes to the output."
# Context: the later matches drop out of the concatenation entirely.
def test_first_limits_the_union_concatenation_to_one_node(run_xjq):
    assert run_xjq("--first", "--text-all", "//a|//b", stdin=PAIR).stdout == "Hello\n"


# Spec: "If `--first` is also active with union + `--text-all`, only the first
#        matched union node contributes to the output."
# Context: that one node still contributes all of its descendant text.
def test_first_union_node_contributes_all_its_text(run_xjq):
    result = run_xjq("--first", "--text-all", "//div|//p", stdin=NESTED)
    assert result.stdout == "Hello World!\n"


# Spec: "If `--first` is also active with union + `--text-all` ..."
# Context: the node-level cut is tied to the concatenation, so `--first` with
# `--text` still cuts to a single text node. See AMBIGUITIES.md T50.
def test_first_with_text_still_cuts_to_one_line(run_xjq):
    assert run_xjq("--first", "-t", "//div|//p", stdin=NESTED).stdout == "Hello\n"


# Spec: "If any union sub-path already performs text extraction, text flags are
#        treated as no-op query modifiers."
# Context: a union of `text()` paths keeps its per-node lines under
# `--text-all` rather than being concatenated.
def test_text_extracting_sub_paths_make_the_flags_no_ops(run_xjq):
    plain = run_xjq("//a/text()|//b/text()", stdin=PAIR)
    assert plain.lines == ["Hello", "World"]
    assert run_xjq("--text-all", "//a/text()|//b/text()", stdin=PAIR).stdout == plain.stdout
    assert run_xjq("-t", "//a/text()|//b/text()", stdin=PAIR).stdout == plain.stdout


# Spec: "If any union sub-path already performs text extraction, text flags are
#        treated as no-op query modifiers."
# Context: one such sub-path is enough — the element sub-path is not extracted
# either, and the results render as the default auto-format would.
# See AMBIGUITIES.md T43 and T44.
def test_one_text_sub_path_disables_extraction_for_all(run_xjq):
    doc = "<r><a>Hello</a><b>Wide <c>World</c></b></r>"
    plain = run_xjq("//a/text()|//b", stdin=doc)
    assert run_xjq("-t", "//a/text()|//b", stdin=doc).stdout == plain.stdout
    assert plain.lines == ["Hello", "Wide World"]


# Spec: "If any union sub-path already performs text extraction ..."
# Context: an attribute sub-path is not text extraction, so the flags still
# apply to the element sub-path. See AMBIGUITIES.md T43.
def test_attribute_sub_path_does_not_disable_extraction(run_xjq):
    doc = "<r><a id='1'/><b>Hello</b></r>"
    assert run_xjq("-t", "//a/@id|//b", stdin=doc).lines == ["1", "Hello"]


# Spec: "`-j`, `--json`: JSON export mode ..." with "Support XPath `|` union"
# Context: a union exports every match from either side.
def test_union_exports_every_match_as_json(run_xjq):
    exported = json.loads(run_xjq("-j", "//a|//b", stdin=PAIR).stdout)
    assert exported == [{"a": "Hello"}, {"b": "World"}]


# Spec: "In CSS mode, pass `|` through as CSS query text (no XPath union
#        semantics). If the CSS engine rejects the selector, report a CSS
#        selector error on stderr with exit code `1`."
# Context: CSS reads `a|b` as a namespace, which this tool cannot resolve.
# See AMBIGUITIES.md T47.
def test_css_pipe_is_a_selector_error(run_xjq):
    result = run_xjq("--css", "a|b", stdin=PAIR)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "css" in result.stderr.lower()


# Spec: "... If the CSS engine rejects the selector, report a CSS selector
#        error on stderr with exit code `1`."
# Context: the spaced spelling a union-minded user would write is rejected by
# the selector parser itself.
def test_css_spaced_pipe_is_a_selector_error(run_xjq):
    result = run_xjq("--css", "a | b", stdin=PAIR)
    assert result.returncode == 1
    assert "css" in result.stderr.lower()


# Spec: "In CSS mode, pass `|` through as CSS query text (no XPath union
#        semantics)."
# Context: the CSS way to match two things is the comma list, and it keeps the
# ordinary CSS text output rather than the union concatenation.
# See AMBIGUITIES.md T48.
def test_css_comma_list_keeps_css_text_rules(run_xjq):
    assert run_xjq("--css", "--text-all", "a, b", stdin=PAIR).lines == ["Hello", "World"]
    assert run_xjq("--css", "a ::text, b ::text", stdin=PAIR).lines == ["Hello", "World"]
