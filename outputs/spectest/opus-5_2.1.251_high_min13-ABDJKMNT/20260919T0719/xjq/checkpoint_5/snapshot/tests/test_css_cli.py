"""Spec section: CLI Additions.

The three new switches exist and each selects the documented query or
extraction mode.
"""

from conftest import CSS_DOC, DOC


# Phrase: "`--css`: interpret QUERY as CSS selector."
def test_css_flag_interprets_query_as_a_css_selector(xjq):
    result = xjq("--css", "span", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stdout == "<span>Span text</span>\n"


# Phrase: "`--css`: interpret QUERY as CSS selector."
# Class and id syntax is CSS, not XPath.
def test_css_flag_supports_class_and_id_selectors(xjq):
    assert xjq("--css", "--text", ".lead", stdin=CSS_DOC).stdout.startswith("Hello")
    assert xjq("--css", "#wrap > span", "--text", stdin=CSS_DOC).stdout == "Span text\n"


# Phrase: "`--css`: interpret QUERY as CSS selector."
# Without the flag the same string is an XPath expression, so a bare tag name
# is a child location path rather than a descendant search: `<b>` is nested two
# levels down and only the CSS reading finds it.
def test_query_is_xpath_without_the_css_flag(xjq):
    assert xjq("b", stdin=CSS_DOC).stdout == ""
    assert xjq("--css", "b", stdin=CSS_DOC).stdout == "<b>bold</b>\n"


# Phrase: "`-t`, `--text`: direct text extraction from matched elements."
def test_text_flag_extracts_direct_text(xjq):
    result = xjq("--css", "--text", "p", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stdout == "Hello\nworld\nSecond\n"


# Phrase: "`-t`, `--text`" -- the short spelling is the same option.
def test_short_text_flag_matches_long_spelling(xjq):
    short = xjq("--css", "-t", "p", stdin=CSS_DOC)
    long = xjq("--css", "--text", "p", stdin=CSS_DOC)
    assert short.stdout == long.stdout
    assert short.returncode == 0


# Phrase: "`-t`, `--text`: direct text extraction from matched elements."
# Direct means the matched element's own text nodes, not a descendant's.
def test_text_flag_ignores_descendant_text(xjq):
    result = xjq("--css", "-t", "section", stdin="<article><section><p>deep</p></section></article>")
    assert result.stdout == ""
    assert result.returncode == 0


# Phrase: "`--text-all`: descendant text extraction from matched elements."
def test_text_all_flag_extracts_descendant_text(xjq):
    result = xjq("--css", "--text-all", "p", stdin=CSS_DOC)
    assert result.returncode == 0
    assert result.stdout == "Hello\nbold\nworld\nSecond\n"


# Phrase: "`--text-all`: descendant text extraction from matched elements."
def test_text_all_reaches_through_nested_elements(xjq):
    result = xjq("--css", "--text-all", "article", stdin="<article><section><p>deep</p></section></article>")
    assert result.stdout == "deep\n"


# Phrase: "`-t`, `--text`" / "`--text-all`" applied to an XPath query (T14).
def test_text_flags_apply_to_xpath_queries_too(xjq):
    assert xjq("--text", "//title", stdin=DOC).stdout == "Dune\nLe Petit Prince\n"
    assert xjq("--text-all", "//book[1]", stdin=DOC).stdout == "Dune\nFrank Herbert\n"
