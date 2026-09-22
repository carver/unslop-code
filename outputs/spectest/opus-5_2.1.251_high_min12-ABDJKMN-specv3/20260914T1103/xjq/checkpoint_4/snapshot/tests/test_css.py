"""Spec section: CSS Query Mode (and the `--css` CLI addition).

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


# --- Phrase: "`--css`: interpret `QUERY` as CSS selector." ----------------
# Context: the flag switches the QUERY positional from XPath to CSS.

def test_css_flag_selects_by_element_name(xjq, books):
    r = xjq("--css", "title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


def test_css_flag_is_accepted_before_the_query(xjq, books):
    r = xjq("--css", "book", stdin=books)
    assert r.returncode == 0
    assert 'id="b1"' in r.stdout


def test_css_class_selector(xjq, page):
    r = xjq("--css", "div.post", stdin=page)
    assert r.returncode == 0
    assert 'id="p1"' in r.stdout


def test_css_id_selector(xjq, page):
    r = xjq("--css", "#p2", stdin=page)
    assert r.returncode == 0
    assert 'id="p2"' in r.stdout


def test_css_attribute_selector(xjq, books):
    r = xjq("--css", "book[lang='fr']", stdin=books)
    assert r.returncode == 0
    assert "Le Petit Prince" in r.stdout


def test_css_descendant_combinator(xjq, books):
    r = xjq("--css", "library book title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


def test_css_child_combinator(xjq, books):
    r = xjq("--css", "book > year", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<year>1965</year>"


def test_without_css_flag_the_query_is_still_xpath(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


def test_css_selector_is_not_evaluated_as_xpath(xjq, books):
    # "title" as XPath is a relative element step from the root; as CSS it is
    # a descendant-or-self match.  Only the CSS reading finds anything here.
    r = xjq("--css", "year", stdin=books)
    assert r.returncode == 0
    assert "1965" in r.stdout


def test_css_no_match_writes_nothing_and_exits_zero(xjq, books):
    r = xjq("--css", "nosuchelement", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


# --- Phrase: "`selector::text` returns direct text" -----------------------
# Context: the custom ::text pseudo-element, attached with no whitespace,
# extracts only the element's own (direct-child) text nodes.

def test_direct_text_pseudo_element(xjq, books):
    r = xjq("--css", "title::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_direct_text_excludes_child_element_text(xjq, mixed):
    # Ambiguity T11: one line per matched element, so <p>'s two direct text
    # nodes are joined; "bold" belongs to <b> and is not direct text of <p>.
    r = xjq("--css", "p::text", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello world"
    assert "bold" not in r.stdout


def test_direct_text_of_element_without_own_text_is_empty(xjq, books):
    # <book> contains only whitespace between its children.
    r = xjq("--css", "book::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_direct_text_one_line_per_matched_element(xjq, page):
    r = xjq("--css", "h2::text", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First", "Second"]


def test_direct_text_with_combinator(xjq, books):
    r = xjq("--css", "book[lang='en'] > author::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Frank Herbert", "William Gibson"]


def test_direct_text_exits_zero_with_no_match(xjq, books):
    r = xjq("--css", "nosuch::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


# --- Phrase: "`selector ::text` returns all descendant text nodes" -------
# Context: a space before ::text switches to descendant extraction.

def test_descendant_text_pseudo_element(xjq, mixed):
    # Ambiguity T12: every text node in the subtree, one per line.
    r = xjq("--css", "p ::text", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Hello", "bold", "world"]


def test_descendant_text_of_container(xjq, books):
    r = xjq("--css", "book[lang='fr'] ::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Le Petit Prince",
        "Antoine de Saint-Exupery",
        "1943",
    ]


# --- Phrase: "(one text node per line)" ----------------------------------
# Context: the descendant form emits one line per text node, not one line
# per matched element.

def test_descendant_text_one_line_per_text_node(xjq):
    doc = "<doc><p>a<b>c</b>d</p></doc>"
    r = xjq("--css", "p ::text", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["a", "c", "d"]


def test_descendant_text_across_multiple_matches_keeps_document_order(xjq, page):
    r = xjq("--css", "div.post ::text", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "First",
        "Hello",
        "bold",
        "world",
        "Second",
        "Bye",
    ]


def test_descendant_text_includes_the_matched_elements_own_text(xjq):
    # Ambiguity T12: ".//text()" - the element's own direct text nodes are
    # descendant text nodes too.
    doc = "<doc><p>own<b>child</b></p></doc>"
    r = xjq("--css", "p ::text", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["own", "child"]


def test_descendant_text_drops_whitespace_only_nodes(xjq, books):
    r = xjq("--css", "library ::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"
    assert "" not in r.stdout.splitlines()


def test_space_before_double_colon_is_significant(xjq, mixed):
    direct = xjq("--css", "p::text", stdin=mixed)
    descendant = xjq("--css", "p ::text", stdin=mixed)
    assert direct.returncode == 0
    assert descendant.returncode == 0
    assert direct.stdout != descendant.stdout


# --- Phrase: "Comma-separated selectors are supported for `::text` queries
#             when all selectors use the same `::text` mode." --------------
# Context: a selector list where every branch is direct-::text, or every
# branch is descendant-::text.

def test_comma_separated_direct_text_selectors(xjq, books):
    r = xjq("--css", "title::text, author::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Dune",
        "Frank Herbert",
        "Le Petit Prince",
        "Antoine de Saint-Exupery",
        "Neuromancer",
        "William Gibson",
    ]


def test_comma_separated_direct_text_exits_zero(xjq, books):
    r = xjq("--css", "title::text, year::text", stdin=books)
    assert r.returncode == 0
    assert r.stderr == ""


def test_comma_separated_descendant_text_selectors(xjq, page):
    r = xjq("--css", "h2 ::text, p ::text", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "First",
        "Hello",
        "bold",
        "world",
        "Second",
        "Bye",
    ]


def test_comma_separated_selectors_without_text_are_supported(xjq, books):
    r = xjq("--css", "title, author", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


def test_comma_separated_tolerates_extra_whitespace(xjq, books):
    r = xjq("--css", "title::text ,   author::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


# --- Phrase: "Mixing direct and descendant `::text` modes in one
#             comma-separated CSS query is invalid (stderr message,
#             exit code `1`)." ---------------------------------------------
# Context: the two ::text modes cannot be combined in one selector list.

def test_mixing_direct_and_descendant_text_modes_exits_one(xjq, books):
    r = xjq("--css", "title::text, author ::text", stdin=books)
    assert r.returncode == 1


def test_mixing_modes_writes_to_stderr(xjq, books):
    r = xjq("--css", "title::text, author ::text", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_mixing_modes_writes_nothing_to_stdout(xjq, books):
    r = xjq("--css", "title::text, author ::text", stdin=books)
    assert r.stdout == ""


def test_mixing_modes_other_order_exits_one(xjq, books):
    r = xjq("--css", "title ::text, author::text", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_mixing_modes_is_not_a_traceback(xjq, books):
    r = xjq("--css", "title::text, author ::text", stdin=books)
    assert "Traceback" not in r.stderr


def test_mixing_text_and_non_text_branches_exits_one(xjq, books):
    # Ambiguity T13: "the same ::text mode" is read as requiring every branch
    # to agree, including branches with no ::text at all.
    r = xjq("--css", "title::text, author", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# --- Phrase: "In CSS mode without text extraction, return XML node output
#             with pretty-print serialization." ---------------------------
# Context: a plain CSS selector behaves like an element-returning XPath.

def test_css_without_text_returns_xml(xjq, books):
    r = xjq("--css", "book", stdin=books)
    assert r.returncode == 0
    assert r.stdout.lstrip().startswith("<book")
    assert "</book>" in r.stdout


def test_css_xml_output_is_pretty_printed(xjq):
    r = xjq("--css", "a", stdin="<a><b><c>deep</c></b></a>")
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 4
    indents = [len(ln) - len(ln.lstrip()) for ln in lines[:3]]
    assert indents[0] < indents[1] < indents[2]


def test_css_xml_output_has_no_trailing_newline(xjq):
    r = xjq("--css", "b", stdin="<a><b>text</b></a>")
    assert r.returncode == 0
    assert not r.stdout.endswith("\n")


def test_css_xml_output_prints_only_the_first_node(xjq, books):
    # Ambiguity T15: the Output section's "output only the first node" rule
    # still governs CSS node results.
    r = xjq("--css", "book", stdin=books)
    assert r.returncode == 0
    assert 'id="b1"' in r.stdout
    assert 'id="b2"' not in r.stdout


def test_css_xml_output_includes_descendants(xjq, books):
    r = xjq("--css", "book", stdin=books)
    assert r.returncode == 0
    assert "<title>Dune</title>" in r.stdout
    assert "Frank Herbert" in r.stdout


def test_css_xml_output_excludes_tail_text(xjq):
    r = xjq("--css", "b", stdin="<a><b>inner</b>TAILTEXT</a>")
    assert r.returncode == 0
    assert "TAILTEXT" not in r.stdout


# --- Phrase: "Invalid CSS selector: stderr message, exit code `1`." -------
# Context: a QUERY that CSS cannot parse or translate.

@pytest.mark.parametrize(
    "selector",
    [
        "div >",
        "[",
        "a::",
        ">>>",
        "p:nosuchpseudoclass",
        "::",
        "",
        "a[",
        "div ()",
    ],
)
def test_invalid_css_selector_exits_one(xjq, selector, books):
    r = xjq("--css", selector, stdin=books)
    assert r.returncode == 1


def test_invalid_css_selector_writes_to_stderr(xjq, books):
    r = xjq("--css", "div >", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_invalid_css_selector_writes_nothing_to_stdout(xjq, books):
    r = xjq("--css", "div >", stdin=books)
    assert r.stdout == ""


def test_invalid_css_message_mentions_css_or_selector(xjq, books):
    r = xjq("--css", "div >", stdin=books)
    lowered = r.stderr.lower()
    assert "css" in lowered or "selector" in lowered


def test_invalid_css_selector_is_not_a_traceback(xjq, books):
    r = xjq("--css", "[", stdin=books)
    assert "Traceback" not in r.stderr


def test_invalid_css_error_message_is_a_single_line(xjq, books):
    r = xjq("--css", "div >", stdin=books)
    assert len(r.stderr.strip().splitlines()) == 1


def test_text_pseudo_element_not_at_end_is_invalid(xjq, books):
    r = xjq("--css", "title::text > author", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_xpath_expression_under_css_flag_is_an_invalid_selector(xjq, books):
    r = xjq("--css", "//title/text()", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""
