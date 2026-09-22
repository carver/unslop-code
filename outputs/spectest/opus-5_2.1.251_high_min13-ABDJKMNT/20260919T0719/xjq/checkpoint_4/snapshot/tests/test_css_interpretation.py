"""Interpretation choices for the CSS spec, recorded in AMBIGUITIES.md.

Each section names the ambiguity entry it pins down.
"""

from conftest import CSS_DOC, NESTED_DOC


# T10: direct text is one result per direct child text node, so mixed content
# spread around a child element becomes several lines.
def test_direct_text_is_one_line_per_text_node(xjq):
    doc = "<r><p>Hello <b>bold</b> world</p></r>"
    assert xjq("--css", "p::text", stdin=doc).stdout == "Hello\nworld\n"


# T10: the same rule applies to the `--text` flag.
def test_direct_text_flag_is_one_line_per_text_node(xjq):
    doc = "<r><p>Hello <b>bold</b> world</p></r>"
    assert xjq("--text", "//p", stdin=doc).stdout == "Hello\nworld\n"


# T11: CSS node output keeps the first-node-only rule of XPath node output.
def test_css_node_output_shows_only_the_first_match(xjq):
    out = xjq("--css", "p", stdin=CSS_DOC).stdout
    assert "Hello" in out
    assert "Second" not in out


# T12: "already extracts text" is decided from the result, so `text()` inside a
# predicate does not silence the flag.
def test_text_in_a_predicate_does_not_silence_the_flag(xjq):
    doc = "<r><p>keep</p><p>drop</p></r>"
    assert xjq("--text", "//p[text()='keep']", stdin=doc).stdout == "keep\n"


# T13: a comma list mixing `::text` with a plain selector is invalid.
def test_mixing_text_and_plain_selectors_is_invalid(xjq):
    result = xjq("--css", "h1::text, section", stdin=NESTED_DOC)
    assert result.returncode == 1
    assert result.stderr.strip() != ""


# T15: descendant extraction drops text nodes that normalize to nothing, so an
# indented document yields no blank lines.
def test_descendant_extraction_drops_whitespace_only_nodes(xjq):
    out = xjq("--css", "article ::text", stdin=NESTED_DOC).stdout
    assert out == "Title\nouter\ninner\ntail\n"
    assert "\n\n" not in out


# T16: descendant extraction includes the element's own direct text nodes.
def test_descendant_extraction_includes_direct_text(xjq):
    doc = "<r><p>own <b>child</b></p></r>"
    assert xjq("--css", "p ::text", stdin=doc).stdout == "own\nchild\n"


# T18: a comma-separated selector list yields matches in document order, not in
# the order the selectors were written.
def test_comma_list_results_follow_document_order(xjq):
    assert xjq("--css", "span::text, p::text", stdin=CSS_DOC).stdout == (
        "Hello\nworld\nSecond\nSpan text\n"
    )
