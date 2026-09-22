"""CSS query mode: selector support, node output, and selector errors."""

import pytest

from conftest import BOOKS, PAGE


# Spec: "`--css`: interpret `QUERY` as CSS selector."
def test_css_flag_selects_by_type_selector(run_xjq):
    result = run_xjq("--css", "title", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "<title>Dune</title>"


# Spec: "`--css`: interpret `QUERY` as CSS selector." -- class, id, attribute,
# descendant, child, and pseudo-class selectors all work.
@pytest.mark.parametrize(
    "selector",
    [".post", "#p1", "div[id='p1']", "body div", "body > div", "div:first-child"],
)
def test_css_selector_forms(run_xjq, selector):
    result = run_xjq("--css", selector, stdin=PAGE)
    assert result.returncode == 0
    assert result.stdout.startswith('<div class="post" id="p1">')


# Spec: "`--css`: interpret `QUERY` as CSS selector." -- the root element itself
# is a candidate match.
def test_css_matches_the_root_element(run_xjq):
    result = run_xjq("--css", "library", stdin=BOOKS)
    assert result.stdout.startswith("<library>")


# Spec: "`--css`: interpret `QUERY` as CSS selector." -- so an XPath expression
# is no longer a valid query.
def test_xpath_is_not_accepted_as_css(run_xjq):
    result = run_xjq("--css", "//book", stdin=BOOKS)
    assert result.returncode == 1
    assert result.stdout == ""


# Spec: "`--css`: interpret `QUERY` as CSS selector." -- without the flag the
# same query is still XPath.
def test_css_is_opt_in(run_xjq):
    assert run_xjq("//title/text()", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "In CSS mode without text extraction, return XML node output with
# pretty-print serialization."
def test_css_node_output_is_pretty_printed(run_xjq):
    result = run_xjq("--css", ".post", stdin=PAGE)
    assert result.stdout.rstrip("\n").split("\n") == [
        '<div class="post" id="p1">',
        "  <h1>First <em>Post</em></h1>",
        '  <p class="body">Hello <b>World</b>!</p>',
        '  <p class="body">Second line</p>',
        "</div>",
    ]


# Spec: "In CSS mode without text extraction, return XML node output ..." --
# node output keeps the base rule that only the first match is serialized.
def test_css_node_output_is_the_first_match_only(run_xjq):
    result = run_xjq("--css", "book", stdin=BOOKS)
    assert result.stdout.count("<book") == 1
    assert "Les Miserables" not in result.stdout


# Spec: "In CSS mode without text extraction ..." -- a selector matching
# nothing is still a successful run with no output.
def test_css_no_match_writes_nothing(run_xjq):
    result = run_xjq("--css", ".missing", stdin=PAGE)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# Spec: "Comma-separated selectors are supported ..." -- comma-separated node
# queries select the union, in document order.
def test_comma_separated_node_selectors(run_xjq):
    result = run_xjq("--css", "em, h1", stdin=PAGE)
    assert result.stdout.rstrip("\n") == "<h1>First <em>Post</em></h1>"


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
@pytest.mark.parametrize("selector", ["<<<", "div::", "div:(", "[", "p..x", ""])
def test_invalid_css_selector_exits_one(run_xjq, selector):
    result = run_xjq("--css", selector, stdin=PAGE)
    assert result.returncode == 1
    assert result.stderr != ""
    assert result.stdout == ""


# Spec: "Invalid CSS selector: stderr message, exit code `1`." -- the message
# names the failing mode.
def test_invalid_css_selector_message_mentions_css(run_xjq):
    result = run_xjq("--css", "div::", stdin=PAGE)
    assert "css" in result.stderr.lower()


# Spec: "Define custom `::text` pseudo-element" -- and only that one; other
# pseudo-elements remain unsupported.
def test_unsupported_pseudo_element_exits_one(run_xjq):
    result = run_xjq("--css", "p::before", stdin=PAGE)
    assert result.returncode == 1
    assert "css" in result.stderr.lower()
