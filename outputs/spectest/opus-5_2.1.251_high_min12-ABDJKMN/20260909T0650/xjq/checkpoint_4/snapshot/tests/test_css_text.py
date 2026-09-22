"""Spec conformance tests for the CSS-selector / text-extraction additions.

Same convention as tests/test_xjq.py: the spec is split into minimal logical
phrases and each section quotes its phrase (plus the minimal context it needs)
in a comment. Interpretation choices are cross-referenced as Tn ->
AMBIGUITIES.md.
"""

import textwrap

import pytest

from conftest import run, run_argv

# ---------------------------------------------------------------------------
# Documents used across sections.
# ---------------------------------------------------------------------------

# Compact on purpose: no indentation whitespace, so text-node lists are exactly
# the authored text and assertions stay unambiguous.
COMPACT = (
    '<root>'
    '<div class="a" id="first">one<span>two</span>three</div>'
    '<div class="b">four</div>'
    '</root>'
)

SIMPLE = "<root><item>a</item><item>b</item><item>c</item></root>"

MIXED_CASE = "<Root><Item>upper</Item><item>lower</item></Root>"

PRETTY = textwrap.dedent(
    """\
    <root>
      <div>
        <p>Hello</p>
        <p>World</p>
      </div>
    </root>
    """
)


# ===========================================================================
# Section 18
# Phrase: "`--css`: interpret `QUERY` as CSS selector."
# Context: CLI Additions.
# ===========================================================================


def test_css_flag_is_accepted():
    r = run_argv(["--css", "div"], COMPACT)
    assert r.returncode == 0
    assert r.stderr == ""


def test_css_type_selector_matches_elements():
    r = run_argv(["--css", "item"], SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "<item>a</item>"


def test_css_selector_matches_anywhere_in_document():
    # A bare type selector is not anchored to the root: `span` finds the
    # nested span, not just children of the document element.
    r = run_argv(["--css", "span"], COMPACT)
    assert r.returncode == 0
    assert r.stdout.strip() == "<span>two</span>"


def test_css_class_selector():
    r = run_argv(["--css", ".b::text"], COMPACT)
    assert r.lines == ["four"]


def test_css_id_selector():
    r = run_argv(["--css", "#first::text"], COMPACT)
    assert r.lines == ["one", "three"]


def test_css_attribute_selector():
    r = run_argv(["--css", '[class="b"]::text'], COMPACT)
    assert r.lines == ["four"]


def test_css_descendant_combinator():
    r = run_argv(["--css", "div span::text"], COMPACT)
    assert r.lines == ["two"]


def test_css_child_combinator():
    r = run_argv(["--css", "root > div::text"], COMPACT)
    assert r.lines == ["one", "three", "four"]


def test_css_nth_child_pseudo_class():
    r = run_argv(["--css", "item:nth-child(2)::text"], SIMPLE)
    assert r.lines == ["b"]


def test_css_mode_does_not_evaluate_xpath():
    # Without --css the same string is an XPath expression; with --css it must
    # be read as CSS. "div" as XPath is a relative path from the root element.
    xpath_style = run("div", COMPACT)
    css_style = run_argv(["--css", "div"], COMPACT)
    assert css_style.returncode == 0
    # XPath `div` selects children of <root>; CSS `div` reaches them too, but
    # the point is that --css must not raise and must find the element.
    assert "<div" in css_style.stdout
    assert xpath_style.returncode == 0


def test_xpath_mode_is_still_the_default():
    r = run("//item[2]/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["b"]


def test_css_query_without_css_flag_is_an_xpath_error():
    # `div::text` is not valid XPath 1.0.
    r = run("div::text", COMPACT)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_css_selector_is_case_sensitive():
    # T16: GenericTranslator (XML semantics), matching the case-sensitive parse.
    upper = run_argv(["--css", "Item::text"], MIXED_CASE)
    lower = run_argv(["--css", "item::text"], MIXED_CASE)
    assert upper.lines == ["upper"]
    assert lower.lines == ["lower"]


def test_css_no_match_is_silent_and_exits_zero():
    r = run_argv(["--css", "nosuchelement"], COMPACT)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_css_accepts_infile_positional(tmp_path):
    # The later file/first/compact spec makes INFILE the input source, so the
    # file's document -- not stdin -- is what CSS mode queries.
    other = tmp_path / "other.xml"
    other.write_text("<root><item>from-file</item></root>")
    r = run_argv(["--css", "item::text", str(other)], SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["from-file"]


# ===========================================================================
# Section 19
# Phrase: "`-t`, `--text`: direct text extraction from matched elements."
# Context: CLI Additions.
# ===========================================================================


def test_short_text_flag_extracts_direct_text():
    r = run_argv(["-t", "--css", "div"], COMPACT)
    assert r.returncode == 0
    # T12: one line per direct child text node.
    assert r.lines == ["one", "three", "four"]


def test_long_text_flag_is_the_same_as_short():
    short = run_argv(["-t", "--css", "div"], COMPACT)
    long = run_argv(["--text", "--css", "div"], COMPACT)
    assert short.stdout == long.stdout


def test_text_flag_excludes_descendant_text():
    r = run_argv(["--text", "--css", "div.a"], COMPACT)
    assert "two" not in r.stdout


def test_text_flag_applies_in_xpath_mode():
    # T11: the flag is a general post-processor, not CSS-only.
    r = run_argv(["-t", "//item"], SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a", "b", "c"]


def test_text_flag_equals_xpath_text_step():
    flagged = run_argv(["-t", "//div"], COMPACT)
    explicit = run("//div/text()", COMPACT)
    assert flagged.stdout == explicit.stdout


def test_text_flag_on_element_with_no_direct_text_yields_nothing():
    r = run_argv(["-t", "--css", "root"], "<root><a>x</a></root>")
    assert r.returncode == 0
    assert r.stdout == ""


def test_text_flag_does_not_serialize_xml():
    r = run_argv(["-t", "--css", "div"], COMPACT)
    assert "<div" not in r.stdout


# ===========================================================================
# Section 20
# Phrase: "`--text-all`: descendant text extraction from matched elements."
# Context: CLI Additions.
# ===========================================================================


def test_text_all_flag_extracts_descendant_text():
    r = run_argv(["--text-all", "--css", "div"], COMPACT)
    assert r.returncode == 0
    assert r.lines == ["one", "two", "three", "four"]


def test_text_all_includes_the_elements_own_direct_text():
    r = run_argv(["--text-all", "--css", "div.a"], COMPACT)
    assert r.lines == ["one", "two", "three"]


def test_text_all_is_in_document_order():
    doc = "<root><d>A<i>B</i>C<i>D</i>E</d></root>"
    r = run_argv(["--text-all", "--css", "d"], doc)
    assert r.lines == ["A", "B", "C", "D", "E"]


def test_text_all_applies_in_xpath_mode():
    r = run_argv(["--text-all", "//div"], COMPACT)
    assert r.lines == ["one", "two", "three", "four"]


def test_text_all_does_not_serialize_xml():
    r = run_argv(["--text-all", "--css", "div"], COMPACT)
    assert "<span" not in r.stdout


def test_text_all_on_element_with_no_text_yields_nothing():
    r = run_argv(["--text-all", "--css", "e"], "<root><e/></root>")
    assert r.returncode == 0
    assert r.stdout == ""


# ===========================================================================
# Section 21
# Phrase: "Define custom `::text` pseudo-element: `selector::text` returns
#          direct text"
# Context: CSS Query Mode.
# ===========================================================================


def test_text_pseudo_element_returns_direct_text():
    r = run_argv(["--css", "div::text"], COMPACT)
    assert r.returncode == 0
    assert r.lines == ["one", "three", "four"]


def test_text_pseudo_element_excludes_descendant_text():
    r = run_argv(["--css", "div::text"], COMPACT)
    assert "two" not in r.stdout


def test_text_pseudo_element_is_equivalent_to_the_text_flag():
    pseudo = run_argv(["--css", "div::text"], COMPACT)
    flag = run_argv(["--text", "--css", "div"], COMPACT)
    assert pseudo.stdout == flag.stdout


def test_text_pseudo_element_on_leaf_elements():
    r = run_argv(["--css", "item::text"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


def test_bare_text_pseudo_element_selects_every_element_text():
    r = run_argv(["--css", "::text"], "<root><a>x</a></root>")
    assert r.returncode == 0
    assert r.lines == ["x"]


def test_text_pseudo_element_produces_no_xml_markup():
    r = run_argv(["--css", "div::text"], COMPACT)
    assert "<" not in r.stdout


# ===========================================================================
# Section 22
# Phrase: "`selector ::text` returns all descendant text nodes
#          (one text node per line)"
# Context: CSS Query Mode -- note the space before `::text`.
# ===========================================================================


def test_descendant_text_pseudo_element_returns_all_text():
    r = run_argv(["--css", "div ::text"], COMPACT)
    assert r.returncode == 0
    assert r.lines == ["one", "two", "three", "four"]


def test_descendant_mode_differs_from_direct_mode():
    direct = run_argv(["--css", "div::text"], COMPACT)
    descendant = run_argv(["--css", "div ::text"], COMPACT)
    assert direct.stdout != descendant.stdout
    assert "two" in descendant.stdout
    assert "two" not in direct.stdout


def test_descendant_text_is_one_text_node_per_line():
    doc = "<root><d>A<i>B</i>C</d></root>"
    r = run_argv(["--css", "d ::text"], doc)
    assert r.lines == ["A", "B", "C"]


def test_descendant_text_is_equivalent_to_the_text_all_flag():
    pseudo = run_argv(["--css", "div ::text"], COMPACT)
    flag = run_argv(["--text-all", "--css", "div"], COMPACT)
    assert pseudo.stdout == flag.stdout


def test_descendant_text_reaches_deeply_nested_nodes():
    doc = "<root><a><b><c>deep</c></b></a></root>"
    r = run_argv(["--css", "a ::text"], doc)
    assert r.lines == ["deep"]


def test_descendant_text_does_not_include_tail_outside_the_match():
    doc = "<root><a>in</a>outside</root>"
    r = run_argv(["--css", "a ::text"], doc)
    assert r.lines == ["in"]


def test_descendant_text_keeps_blank_text_nodes_as_blank_lines():
    # T15: strip+collapse with no filtering step, so indentation whitespace
    # between elements contributes empty lines.
    r = run_argv(["--css", "div ::text"], PRETTY)
    assert r.returncode == 0
    assert [line for line in r.lines if line] == ["Hello", "World"]
    assert r.lines == ["", "Hello", "", "World", ""]


# ===========================================================================
# Section 23
# Phrase: "Comma-separated selectors are supported for `::text` queries when
#          all selectors use the same `::text` mode."
# Context: CSS Query Mode.
# ===========================================================================


def test_comma_separated_direct_text_selectors():
    doc = "<root><a>1</a><b>2</b><c>3</c></root>"
    r = run_argv(["--css", "a::text, b::text"], doc)
    assert r.returncode == 0
    assert r.lines == ["1", "2"]


def test_comma_separated_descendant_text_selectors():
    doc = "<root><a>1<i>x</i></a><b>2</b><c>3</c></root>"
    r = run_argv(["--css", "a ::text, b ::text"], doc)
    assert r.returncode == 0
    assert r.lines == ["1", "x", "2"]


def test_comma_separated_results_are_in_document_order():
    # T18: a selector list is a set, returned in document order.
    doc = "<root><b>2</b><a>1</a></root>"
    r = run_argv(["--css", "a::text, b::text"], doc)
    assert r.lines == ["2", "1"]


def test_comma_separated_selectors_without_text_are_supported():
    doc = "<root><a>1</a><b>2</b></root>"
    r = run_argv(["--css", "a, b"], doc)
    assert r.returncode == 0
    assert r.stderr == ""


def test_comma_separated_without_spaces_after_comma():
    doc = "<root><a>1</a><b>2</b></root>"
    r = run_argv(["--css", "a::text,b::text"], doc)
    assert r.returncode == 0
    assert r.lines == ["1", "2"]


def test_three_comma_separated_text_selectors():
    doc = "<root><a>1</a><b>2</b><c>3</c></root>"
    r = run_argv(["--css", "a::text, b::text, c::text"], doc)
    assert r.lines == ["1", "2", "3"]


def test_comma_separated_duplicate_matches_are_not_repeated():
    doc = '<root><a class="x">1</a></root>'
    r = run_argv(["--css", "a::text, .x::text"], doc)
    assert r.lines == ["1"]


# ===========================================================================
# Section 24
# Phrase: "Mixing direct and descendant `::text` modes in one comma-separated
#          CSS query is invalid (stderr message, exit code `1`)."
# Context: CSS Query Mode.
# ===========================================================================

MIXED_MODE_QUERIES = [
    "a::text, b ::text",
    "a ::text, b::text",
    "a::text, b::text, c ::text",
    "div p::text, div ::text",
]


@pytest.mark.parametrize("query", MIXED_MODE_QUERIES)
def test_mixed_text_modes_exit_one(query):
    r = run_argv(["--css", query], COMPACT)
    assert r.returncode == 1


@pytest.mark.parametrize("query", MIXED_MODE_QUERIES)
def test_mixed_text_modes_write_to_stderr(query):
    r = run_argv(["--css", query], COMPACT)
    assert r.stderr.strip() != ""


@pytest.mark.parametrize("query", MIXED_MODE_QUERIES)
def test_mixed_text_modes_write_nothing_to_stdout(query):
    assert run_argv(["--css", query], COMPACT).stdout == ""


def test_mixed_text_modes_message_mentions_text_or_mode():
    r = run_argv(["--css", "a::text, b ::text"], COMPACT)
    low = r.stderr.lower()
    assert "text" in low or "mode" in low or "mix" in low


def test_mixing_text_and_node_selectors_is_invalid():
    # T17: "no ::text" counts as a third mode; a half-text query has no
    # coherent output mode.
    r = run_argv(["--css", "a::text, b"], COMPACT)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_single_selector_is_never_a_mode_conflict():
    assert run_argv(["--css", "div ::text"], COMPACT).returncode == 0
    assert run_argv(["--css", "div::text"], COMPACT).returncode == 0


# ===========================================================================
# Section 25
# Phrase: "In CSS mode without text extraction, return XML node output with
#          pretty-print serialization."
# Context: CSS Query Mode.
# ===========================================================================


def test_css_without_text_returns_xml_node():
    r = run_argv(["--css", "item"], SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip().startswith("<item")


def test_css_node_output_is_pretty_printed():
    doc = "<root><a><b>1</b><c>2</c></a></root>"
    r = run_argv(["--css", "a"], doc)
    lines = r.stdout.rstrip("\n").split("\n")
    assert lines[0] == "<a>"
    assert lines[1].startswith(" ")
    assert lines[-1] == "</a>"


def test_css_node_output_matches_xpath_node_output():
    doc = "<root><a><b>1</b></a></root>"
    assert run_argv(["--css", "a"], doc).stdout == run("//a", doc).stdout


def test_css_node_output_keeps_attributes():
    r = run_argv(["--css", "div.b"], COMPACT)
    assert 'class="b"' in r.stdout


def test_css_node_output_has_no_xml_declaration():
    assert "<?xml" not in run_argv(["--css", "root"], SIMPLE).stdout


def test_css_multiple_node_matches_output_only_the_first():
    # T14: "XML node output" carries the round-1 first-node-only rule.
    r = run_argv(["--css", "item"], SIMPLE)
    assert r.stdout.strip() == "<item>a</item>"
    assert "b" not in r.stdout


def test_css_node_output_is_reparseable():
    from lxml import etree

    doc = "<root><a id='1'><b>x</b><c><d>y</d></c></a></root>"
    r = run_argv(["--css", "a"], doc)
    node = etree.fromstring(r.stdout)
    assert node.tag == "a"
    assert node.findtext("b") == "x"


# ===========================================================================
# Section 26
# Phrase: "Invalid CSS selector: stderr message, exit code `1`."
# Context: CSS Query Mode.
# ===========================================================================

BAD_CSS = [
    "div >",            # dangling combinator
    "[",                # unterminated attribute selector
    "a[",               # unterminated attribute selector
    ")",                # stray delimiter
    "",                 # empty selector
    "a::bogus",         # unknown pseudo-element
    "a:nosuchclass",    # unknown pseudo-class
    "a{b}",             # not a selector at all
]


@pytest.mark.parametrize("query", BAD_CSS)
def test_invalid_css_exits_one(query):
    assert run_argv(["--css", query], SIMPLE).returncode == 1


@pytest.mark.parametrize("query", BAD_CSS)
def test_invalid_css_writes_message_to_stderr(query):
    assert run_argv(["--css", query], SIMPLE).stderr.strip() != ""


@pytest.mark.parametrize("query", BAD_CSS)
def test_invalid_css_writes_nothing_to_stdout(query):
    assert run_argv(["--css", query], SIMPLE).stdout == ""


def test_invalid_css_message_mentions_css_or_selector():
    r = run_argv(["--css", "div >"], SIMPLE)
    low = r.stderr.lower()
    assert "css" in low or "selector" in low


def test_valid_xpath_is_still_invalid_css():
    r = run_argv(["--css", "//item"], SIMPLE)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# ===========================================================================
# Section 27
# Phrase: "Multi-match text output joins lines with `\n`."
# Context: Text Extraction.
# ===========================================================================


def test_multi_match_text_joins_with_newline():
    r = run_argv(["--css", "item::text"], SIMPLE)
    assert r.stdout.split("\n")[:3] == ["a", "b", "c"]


def test_multi_match_text_has_one_line_per_result():
    r = run_argv(["--css", "item::text"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


def test_single_match_text_is_a_single_line():
    r = run_argv(["--css", "div.b::text"], COMPACT)
    assert r.lines == ["four"]


def test_multi_match_text_flag_joins_with_newline():
    r = run_argv(["-t", "--css", "item"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


def test_multiline_text_node_becomes_one_line():
    doc = "<root><a>first\nsecond</a><b>third</b></root>"
    r = run_argv(["--css", "a::text, b::text"], doc)
    assert r.lines == ["first second", "third"]


def test_no_text_matches_writes_nothing():
    r = run_argv(["--css", "nosuch::text"], SIMPLE)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ===========================================================================
# Section 28
# Phrase: "Strip each result and collapse internal whitespace runs to single
#          spaces."
# Context: Text Extraction.
# ===========================================================================


def test_text_result_is_stripped():
    doc = "<root><a>   padded   </a></root>"
    assert run_argv(["--css", "a::text"], doc).lines == ["padded"]


def test_text_result_internal_runs_are_collapsed():
    doc = "<root><a>lots    of     space</a></root>"
    assert run_argv(["--css", "a::text"], doc).lines == ["lots of space"]


def test_text_result_newlines_and_tabs_are_collapsed():
    doc = "<root><a>a\n\tb\r\n  c</a></root>"
    assert run_argv(["--css", "a::text"], doc).lines == ["a b c"]


def test_each_text_result_is_stripped_independently():
    doc = "<root><a>  x  </a><a>\n y \n</a></root>"
    assert run_argv(["--css", "a::text"], doc).lines == ["x", "y"]


def test_text_flag_results_are_stripped_and_collapsed():
    doc = "<root><a>  spaced    out  </a></root>"
    assert run_argv(["-t", "--css", "a"], doc).lines == ["spaced out"]


def test_text_all_results_are_stripped_and_collapsed():
    doc = "<root><a>  outer   text <i>  inner   text </i></a></root>"
    assert run_argv(["--text-all", "--css", "a"], doc).lines == [
        "outer text",
        "inner text",
    ]


# ===========================================================================
# Section 29
# Phrase: "If both `--text` and `--text-all` are present, `--text-all` wins."
# Context: Flag Rules.
# ===========================================================================


def test_text_all_wins_over_text():
    r = run_argv(["--text", "--text-all", "--css", "div.a"], COMPACT)
    assert r.returncode == 0
    assert r.lines == ["one", "two", "three"]


def test_text_all_wins_regardless_of_flag_order():
    a = run_argv(["--text", "--text-all", "--css", "div.a"], COMPACT)
    b = run_argv(["--text-all", "--text", "--css", "div.a"], COMPACT)
    assert a.stdout == b.stdout
    assert "two" in a.stdout


def test_text_all_wins_with_short_text_flag():
    r = run_argv(["-t", "--text-all", "--css", "div.a"], COMPACT)
    assert r.lines == ["one", "two", "three"]


def test_both_flags_equal_text_all_alone():
    both = run_argv(["-t", "--text-all", "--css", "div"], COMPACT)
    only = run_argv(["--text-all", "--css", "div"], COMPACT)
    assert both.stdout == only.stdout


def test_both_flags_in_xpath_mode():
    r = run_argv(["-t", "--text-all", "//div"], COMPACT)
    assert r.lines == ["one", "two", "three", "four"]


# ===========================================================================
# Section 30
# Phrase: "If query already extracts text (`text()` or `::text`), `--text` and
#          `--text-all` are no-op modifiers."
# Context: Flag Rules.
# ===========================================================================


def test_text_flag_is_a_noop_for_xpath_text_query():
    plain = run("//item/text()", SIMPLE)
    flagged = run_argv(["-t", "//item/text()"], SIMPLE)
    assert flagged.stdout == plain.stdout
    assert flagged.lines == ["a", "b", "c"]


def test_text_all_flag_is_a_noop_for_xpath_text_query():
    plain = run("//item/text()", SIMPLE)
    flagged = run_argv(["--text-all", "//item/text()"], SIMPLE)
    assert flagged.stdout == plain.stdout


def test_text_flag_is_a_noop_for_css_text_pseudo_element():
    plain = run_argv(["--css", "div::text"], COMPACT)
    flagged = run_argv(["-t", "--css", "div::text"], COMPACT)
    assert flagged.stdout == plain.stdout


def test_text_all_flag_is_a_noop_for_direct_text_pseudo_element():
    # --text-all must not upgrade `div::text` into descendant mode.
    plain = run_argv(["--css", "div::text"], COMPACT)
    flagged = run_argv(["--text-all", "--css", "div::text"], COMPACT)
    assert flagged.stdout == plain.stdout
    assert "two" not in flagged.stdout


def test_text_flag_is_a_noop_for_descendant_text_pseudo_element():
    # --text must not downgrade `div ::text` into direct mode.
    plain = run_argv(["--css", "div ::text"], COMPACT)
    flagged = run_argv(["-t", "--css", "div ::text"], COMPACT)
    assert flagged.stdout == plain.stdout
    assert "two" in flagged.stdout


def test_text_flag_is_a_noop_for_attribute_results():
    plain = run("//div/@class", COMPACT)
    flagged = run_argv(["-t", "//div/@class"], COMPACT)
    assert flagged.stdout == plain.stdout
    assert flagged.lines == ["a", "b"]


def test_text_flag_is_a_noop_for_numeric_results():
    flagged = run_argv(["-t", "count(//item)"], SIMPLE)
    assert flagged.stdout == run("count(//item)", SIMPLE).stdout


def test_text_flag_is_a_noop_for_string_function_results():
    flagged = run_argv(["--text", "string(//item[1])"], SIMPLE)
    assert flagged.stdout == run("string(//item[1])", SIMPLE).stdout


def test_text_flag_applies_when_text_is_only_used_in_a_predicate():
    # T13: detection is by result type, not by substring; this query returns
    # elements, so -t still extracts their text.
    r = run_argv(["-t", "//item[text()='b']"], SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["b"]


# ===========================================================================
# Section 31 -- interactions between phrases (integration)
# Context: whole-spec sanity checks over one realistic document.
# ===========================================================================

PAGE = (
    '<html><body>'
    '<ul class="list"><li>Alpha</li><li>Beta <b>bold</b> tail</li></ul>'
    '<p id="note">  Note   text  </p>'
    '</body></html>'
)


def test_integration_css_text_list_items():
    r = run_argv(["--css", "li::text"], PAGE)
    assert r.returncode == 0
    assert r.lines == ["Alpha", "Beta", "tail"]


def test_integration_css_descendant_text_list_items():
    r = run_argv(["--css", "li ::text"], PAGE)
    assert r.lines == ["Alpha", "Beta", "bold", "tail"]


def test_integration_css_text_flag_matches_pseudo_element():
    assert (
        run_argv(["-t", "--css", "li"], PAGE).stdout
        == run_argv(["--css", "li::text"], PAGE).stdout
    )


def test_integration_css_id_selector_collapses_whitespace():
    assert run_argv(["--css", "#note::text"], PAGE).lines == ["Note text"]


def test_integration_css_comma_list():
    r = run_argv(["--css", "#note::text, li::text"], PAGE)
    assert r.lines == ["Alpha", "Beta", "tail", "Note text"]


def test_integration_css_node_output():
    r = run_argv(["--css", "ul.list"], PAGE)
    assert r.returncode == 0
    assert r.stdout.startswith('<ul class="list">')


def test_integration_css_mixed_modes_is_an_error():
    r = run_argv(["--css", "li::text, p ::text"], PAGE)
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr.strip() != ""


def test_integration_malformed_input_still_errors_in_css_mode():
    r = run_argv(["--css", "li::text"], "<html><body><li>x</body></html>")
    assert r.returncode == 1
    low = r.stderr.lower()
    assert "xml" in low or "parse" in low
