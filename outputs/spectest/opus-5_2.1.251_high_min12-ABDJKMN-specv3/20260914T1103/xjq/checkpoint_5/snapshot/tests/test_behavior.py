"""Spec section: Behavior.

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


# --- Phrase: "Parse stdin as XML/HTML" (XML) ------------------------------
# Context: well-formed XML documents are queryable.

def test_parses_plain_xml(xjq):
    r = xjq("//b/text()", stdin="<a><b>hello</b></a>")
    assert r.returncode == 0
    assert r.stdout == "hello"


def test_parses_xml_with_declaration(xjq):
    doc = '<?xml version="1.0" encoding="UTF-8"?><a><b>declared</b></a>'
    r = xjq("//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "declared"


def test_parses_xml_with_comments_and_processing_instructions(xjq):
    doc = '<?xml version="1.0"?><!-- lead --><?pi go?><a><b>v</b></a>'
    r = xjq("//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "v"


def test_parses_utf8_content(xjq):
    doc = '<?xml version="1.0" encoding="UTF-8"?><a><b>café 中文</b></a>'
    r = xjq("//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "café 中文"


def test_resolves_entities_in_text(xjq):
    r = xjq("//b/text()", stdin="<a><b>x &amp; y &lt; z</b></a>")
    assert r.returncode == 0
    assert r.stdout == "x & y < z"


def test_parses_cdata_as_text(xjq):
    r = xjq("//b/text()", stdin="<a><b><![CDATA[raw <not> markup]]></b></a>")
    assert r.returncode == 0
    assert r.stdout == "raw <not> markup"


# --- Phrase: "Parse stdin as XML/HTML" (HTML) -----------------------------
# Context: ambiguity T2 - HTML documents are queryable too.

def test_parses_wellformed_html_document(xjq):
    doc = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
    r = xjq("//p/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "Body text"


def test_parses_html_with_void_elements(xjq):
    # Ambiguity T2: an <html> document with unclosed void tags still parses.
    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body><p>one<br>two</p><img src='x.png'></body></html>"
    )
    r = xjq("//img/@src", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "x.png"


def test_parses_html_attributes(xjq):
    doc = "<html><body><a href='https://example.com'>link</a></body></html>"
    r = xjq("//a/@href", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "https://example.com"


# --- Phrase: "using case-sensitive element matching" ----------------------
# Context: element names differing only in case are distinct.

def test_element_match_is_case_sensitive(xjq):
    doc = "<Root><Book>upper</Book><book>lower</book></Root>"
    r = xjq("//Book/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "upper"


def test_lowercase_query_does_not_match_uppercase_element(xjq):
    doc = "<Root><Book>upper</Book></Root>"
    r = xjq("//book/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == ""


def test_mixed_case_element_names_are_preserved(xjq):
    doc = "<Root><bookTitle>Dune</bookTitle></Root>"
    r = xjq("//bookTitle/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "Dune"
    r2 = xjq("//booktitle/text()", stdin=doc)
    assert r2.returncode == 0
    assert r2.stdout == ""


def test_attribute_names_are_case_sensitive(xjq):
    doc = '<Root><item ID="upper" id="lower"/></Root>'
    r = xjq("//item/@ID", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "upper"


def test_root_element_case_is_preserved(xjq):
    doc = "<LibraryCatalog><x>1</x></LibraryCatalog>"
    r = xjq("/LibraryCatalog/x/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "1"


# --- Phrase: "Evaluate `QUERY` with XPath 1.0." ---------------------------
# Context: XPath 1.0 axes, predicates, and function library.

def test_predicate_by_position(xjq, books):
    r = xjq("//book[2]/title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Le Petit Prince"


def test_predicate_by_attribute_value(xjq, books):
    r = xjq("//book[@lang='fr']/title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Le Petit Prince"


def test_last_function(xjq, books):
    r = xjq("//book[last()]/title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Neuromancer"


def test_contains_function(xjq, books):
    r = xjq("//title[contains(., 'Prince')]/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Le Petit Prince"


def test_numeric_comparison_in_predicate(xjq, books):
    r = xjq("//book[year > 1950]/title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Neuromancer"]


def test_union_of_two_text_node_sets(xjq, books):
    r = xjq("//book[1]/title/text() | //book[1]/year/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "1965"]


def test_ancestor_and_parent_axes(xjq, books):
    r = xjq("//title[text()='Dune']/parent::book/@id", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "b1"


def test_following_sibling_axis(xjq, books):
    r = xjq("//title[text()='Dune']/following-sibling::author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Frank Herbert"


def test_descendant_or_self_abbreviation(xjq, books):
    r = xjq("/library//year/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1965", "1943", "1984"]


def test_string_function_returns_string_value(xjq):
    r = xjq("string(//b)", stdin="<a><b>val</b></a>")
    assert r.returncode == 0
    assert r.stdout == "val"


def test_concat_function(xjq, books):
    r = xjq("concat(//book[1]/title, ' / ', //book[1]/year)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune / 1965"


def test_xpath_2_0_only_syntax_is_not_available(xjq, books):
    # XPath 1.0 has no `if/then/else`; XPath 1.0 engines reject it.
    r = xjq("if (//book) then 'y' else 'n'", stdin=books)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


def test_count_function_evaluates(xjq, books):
    # Ambiguity T3 governs the exact rendering; here only success is asserted.
    r = xjq("count(//book)", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() != ""


# --- Phrase: "Exit code `0` on successful execution" ----------------------
# Context: a query that evaluates without error exits 0.

def test_exit_zero_on_successful_query(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0


def test_exit_zero_writes_nothing_to_stderr(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.stderr == ""


# --- Phrase: "including zero matches" -------------------------------------
# Context: an empty node-set is success, not failure.

def test_exit_zero_when_no_element_matches(xjq, books):
    r = xjq("//nonexistent", stdin=books)
    assert r.returncode == 0


def test_exit_zero_when_no_text_matches(xjq, books):
    r = xjq("//nonexistent/text()", stdin=books)
    assert r.returncode == 0


def test_exit_zero_when_no_attribute_matches(xjq, books):
    r = xjq("//book/@isbn", stdin=books)
    assert r.returncode == 0


def test_exit_zero_when_predicate_filters_everything(xjq, books):
    r = xjq("//book[@lang='de']/title/text()", stdin=books)
    assert r.returncode == 0


def test_exit_zero_for_empty_string_result(xjq, books):
    r = xjq("string(//nonexistent)", stdin=books)
    assert r.returncode == 0
