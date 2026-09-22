"""Spec section: CSS Query Mode.

The custom `::text` pseudo-element, comma-separated selector lists, node
output, and the two ways a CSS query can be rejected.
"""

import pytest

from conftest import CSS_DOC, NESTED_DOC


# Phrase: "Define custom `::text` pseudo-element"
# `::text` is ours, not something the CSS-to-XPath layer already knows.
def test_text_pseudo_element_is_accepted(xjq):
    result = xjq("--css", "span::text", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == "Span text\n"


# Phrase: "`selector::text` returns direct text"
def test_direct_text_pseudo_element(xjq):
    result = xjq("--css", "p::text", stdin=CSS_DOC)
    assert result.stdout == "Hello\nworld\nSecond\n"


# Phrase: "`selector::text` returns direct text"
# Text owned by a descendant is not direct text.
def test_direct_text_excludes_descendant_text(xjq):
    result = xjq("--css", "section::text", stdin=NESTED_DOC)
    assert result.returncode == 0
    assert result.stdout == ""


# Phrase: "`selector ::text` returns all descendant text nodes"
def test_descendant_text_pseudo_element(xjq):
    result = xjq("--css", "p ::text", stdin=CSS_DOC)
    assert result.stdout == "Hello\nbold\nworld\nSecond\n"


# Phrase: "(one text node per line)"
# One mixed-content element becomes three lines, one per text node.
def test_descendant_text_puts_one_text_node_per_line(xjq):
    result = xjq("--css", "section ::text", stdin=NESTED_DOC)
    assert result.stdout == "outer\ninner\ntail\n"


# Phrase: "`selector::text` ... `selector ::text`"
# The space before `::text` is what distinguishes the two modes.
def test_space_before_pseudo_element_selects_descendant_mode(xjq):
    direct = xjq("--css", "article::text", stdin=NESTED_DOC)
    descendant = xjq("--css", "article ::text", stdin=NESTED_DOC)
    assert direct.stdout == ""
    assert descendant.stdout == "Title\nouter\ninner\ntail\n"


# Phrase: "Comma-separated selectors are supported for `::text` queries when
#          all selectors use the same `::text` mode." (direct mode)
def test_comma_separated_direct_text_selectors(xjq):
    result = xjq("--css", "h1::text, em::text", stdin=NESTED_DOC)
    assert result.returncode == 0
    assert result.stdout == "Title\ninner\n"


# Phrase: "Comma-separated selectors are supported ..." (descendant mode)
def test_comma_separated_descendant_text_selectors(xjq):
    result = xjq("--css", "h1 ::text, section ::text", stdin=NESTED_DOC)
    assert result.returncode == 0
    assert result.stdout == "Title\nouter\ninner\ntail\n"


# Phrase: "Comma-separated selectors are supported ..."
# Whitespace around the comma is incidental formatting.
def test_comma_separated_selectors_tolerate_spacing(xjq):
    tight = xjq("--css", "h1::text,em::text", stdin=NESTED_DOC)
    loose = xjq("--css", "h1::text ,  em::text", stdin=NESTED_DOC)
    assert tight.stdout == loose.stdout == "Title\ninner\n"


# Phrase: "Mixing direct and descendant `::text` modes in one comma-separated
#          CSS query is invalid (stderr message, exit code `1`)."
@pytest.mark.parametrize(
    "query",
    [
        "h1::text, section ::text",
        "section ::text, h1::text",
        "h1::text, em::text, section ::text",
    ],
)
def test_mixing_text_modes_is_invalid(xjq, query):
    result = xjq("--css", query, stdin=NESTED_DOC)
    assert result.returncode == 1
    assert result.stderr.strip() != ""
    assert result.stdout == ""


# Phrase: "In CSS mode without text extraction, return XML node output with
#          pretty-print serialization."
def test_css_mode_returns_pretty_printed_xml(xjq):
    result = xjq("--css", "book", stdin="<library><book><title>Dune</title></book></library>")
    assert result.returncode == 0
    assert result.stdout == "<book>\n  <title>Dune</title>\n</book>\n"


# Phrase: "In CSS mode without text extraction, return XML node output ..."
# Attributes survive serialization, as in XPath mode.
def test_css_node_output_keeps_attributes(xjq):
    result = xjq("--css", "span", stdin=CSS_DOC)
    assert result.stdout == "<span>Span text</span>\n"


# Phrase: "In CSS mode without text extraction, return XML node output ..."
# A CSS query matching nothing is still a clean, silent success.
def test_css_query_with_no_matches_is_silent(xjq):
    result = xjq("--css", "table", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# Phrase: "Invalid CSS selector: stderr message, exit code `1`."
@pytest.mark.parametrize(
    "query",
    [
        "p((",              # unbalanced parenthesis
        "a##b",             # stray combinator-less delimiter
        "div >",            # trailing combinator
        "[unclosed",        # unterminated attribute selector
        "p:nonsense",       # unknown pseudo-class
        "::text",           # pseudo-element with nothing to match
    ],
)
def test_invalid_css_selector_exits_one(xjq, query):
    result = xjq("--css", query, stdin=CSS_DOC)
    assert result.returncode == 1
    assert result.stderr.strip() != ""
    assert result.stdout == ""


# Phrase: "Invalid CSS selector: stderr message, exit code `1`." (T17)
def test_invalid_css_message_names_the_stage(xjq):
    message = xjq("--css", "p((", stdin=CSS_DOC).stderr.lower()
    assert "css" in message and "selector" in message


# Phrase: "`--css`: interpret QUERY as CSS selector."
# XPath syntax is not a CSS selector.
def test_xpath_query_is_rejected_in_css_mode(xjq):
    result = xjq("--css", "//p/text()", stdin=CSS_DOC)
    assert result.returncode == 1
    assert result.stderr.strip() != ""
