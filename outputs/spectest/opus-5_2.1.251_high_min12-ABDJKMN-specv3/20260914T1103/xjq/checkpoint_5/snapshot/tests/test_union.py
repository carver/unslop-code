"""Spec section: XPath Union.

Covers `|` union support in XPath mode, how the text flags behave across a
union, and the CSS-mode pass-through.  Each test section quotes the minimal
spec phrase it covers.
"""
import json

import pytest


# --- Phrase: "Support XPath `|` union in XPath mode." --------------------
# Context: a union query is evaluated, not rejected.

def test_union_query_is_accepted(xjq, books):
    r = xjq("//title | //author", stdin=books)
    assert r.returncode == 0
    assert r.stderr == ""


def test_union_matches_both_sub_paths(xjq, books):
    r = xjq("count(//title | //author)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "6"


def test_union_without_spaces_is_accepted(xjq, books):
    r = xjq("count(//title|//author)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "6"


def test_union_of_three_sub_paths(xjq, books):
    r = xjq("count(//title | //author | //year)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "9"


def test_union_node_output_prints_the_first_node(xjq, books):
    # No output flags: the default XML-node rule still applies.
    r = xjq("//title | //author", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_union_result_is_in_document_order(xjq, books):
    r = xjq("-t", "//author | //title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[:2] == ["Dune", "Frank Herbert"]


def test_union_deduplicates_overlapping_sub_paths(xjq, books):
    r = xjq("count(//title | //title)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "3"


def test_union_with_predicates(xjq, books):
    r = xjq("count(//book[@lang='en']/title | //book[@lang='fr']/author)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "3"


def test_union_with_json_export(xjq, books):
    data = json.loads(xjq("-j", "//book[1]/title | //book[1]/year", stdin=books).stdout)
    assert data == [{"title": "Dune"}, {"year": "1965"}]


def test_union_where_one_branch_has_no_match(xjq, books):
    r = xjq("-t", "//nosuch | //title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


# --- Phrase: "`--text` and `--text-all` apply across union queries." -----
# Context: the flags are not disabled by the union; every match is covered.

def test_text_flag_applies_to_every_union_branch(xjq, books):
    r = xjq("-t", "//book[1]/title | //book[1]/author", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Frank Herbert"]


def test_text_flag_across_union_is_one_line_per_element(xjq, books):
    r = xjq("--text", "//title | //author", stdin=books)
    assert r.returncode == 0
    assert len(r.stdout.splitlines()) == 6


def test_text_flag_across_union_keeps_direct_text_only(xjq, page):
    r = xjq("-t", "//h2 | //p", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First", "Hello world", "Second", "Bye"]


def test_text_all_applies_across_union(xjq, page):
    r = xjq("--text-all", "//h2 | //p", stdin=page)
    assert r.returncode == 0
    assert "bold" in r.stdout
    assert "First" in r.stdout and "Bye" in r.stdout


def test_union_text_output_is_not_xml(xjq, books):
    r = xjq("-t", "//title | //author", stdin=books)
    assert "<title>" not in r.stdout


# --- Phrase: "For XPath union queries with active `--text-all`,
#             concatenate descendant text across all union matches into one
#             normalized output string." ---------------------------------
# Context: unlike the one-line-per-element rule, a union collapses to a
# single output string.

def test_union_text_all_is_a_single_line(xjq, books):
    r = xjq("--text-all", "//title | //author", stdin=books)
    assert r.returncode == 0
    assert len(r.stdout.splitlines()) == 1


def test_union_text_all_concatenates_all_matches(xjq, books):
    r = xjq("--text-all", "//book[1]/title | //book[1]/author", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "DuneFrank Herbert"


def test_union_text_all_includes_descendant_text(xjq, page):
    r = xjq("--text-all", "//h2 | //p", stdin=page)
    assert r.returncode == 0
    assert r.stdout == "FirstHello bold worldSecondBye"


def test_union_text_all_output_is_normalized(xjq):
    doc = "<doc><a>  one\n  two  </a><b>\tthree  </b></doc>"
    r = xjq("--text-all", "//a | //b", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "one two three"


def test_union_text_all_covers_every_match(xjq, books):
    r = xjq("--text-all", "//title | //author", stdin=books)
    assert "Dune" in r.stdout
    assert "William Gibson" in r.stdout


def test_non_union_text_all_still_one_line_per_element(xjq, books):
    r = xjq("--text-all", "//title", stdin=books)
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


def test_union_text_all_differs_from_union_text(xjq, books):
    all_text = xjq("--text-all", "//title | //author", stdin=books)
    direct = xjq("--text", "//title | //author", stdin=books)
    assert len(all_text.stdout.splitlines()) == 1
    assert len(direct.stdout.splitlines()) == 6


def test_union_text_all_with_a_container_branch(xjq, books):
    r = xjq("--text-all", "//book[3] | //book[3]/title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Neuromancer William Gibson 1984 Neuromancer"


# --- Phrase: "If `--first` is also active with union + `--text-all`, only
#             the first matched union node contributes to the output." ----
# Context: --first cuts the concatenation down to a single node.

def test_first_with_union_text_all_uses_one_node(xjq, books):
    r = xjq("--text-all", "-f", "//title | //author", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_first_with_union_text_all_drops_later_matches(xjq, page):
    r = xjq("--text-all", "--first", "//h2 | //p", stdin=page)
    assert r.returncode == 0
    assert r.stdout == "First"


def test_first_union_node_is_in_document_order(xjq, books):
    # The first node of the merged result, not of the first sub-path.
    r = xjq("--text-all", "-f", "//author | //title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_first_with_union_text_all_is_a_single_line(xjq, page):
    r = xjq("--text-all", "-f", "//h2 | //p", stdin=page)
    assert len(r.stdout.splitlines()) == 1


def test_first_with_union_text_keeps_one_line(xjq, books):
    r = xjq("--text", "-f", "//title | //author", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


# --- Phrase: "If any union sub-path already performs text extraction, text
#             flags are treated as no-op query modifiers." ---------------
# Context: a `text()` branch in the union disables the flags' rewriting.

def test_union_of_text_paths_with_text_all_is_not_concatenated(xjq, books):
    r = xjq("--text-all", "//title/text() | //author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Dune",
        "Frank Herbert",
        "Le Petit Prince",
        "Antoine de Saint-Exupery",
        "Neuromancer",
        "William Gibson",
    ]


def test_union_of_text_paths_with_text_flag_is_unchanged(xjq, books):
    with_flag = xjq("-t", "//title/text() | //author/text()", stdin=books)
    without = xjq("//title/text() | //author/text()", stdin=books)
    assert with_flag.returncode == 0
    assert with_flag.stdout == without.stdout


def test_one_text_branch_disables_text_all_concatenation(xjq, books):
    r = xjq("--text-all", "//title/text() | //author", stdin=books)
    assert r.returncode == 0
    assert len(r.stdout.splitlines()) > 1


def test_text_extracting_union_branch_with_json_flag(xjq, books):
    r = xjq("-j", "//title/text() | //author/text()", stdin=books)
    assert r.returncode == 0
    assert not r.stdout.startswith("[")


def test_text_flags_remain_no_op_for_text_union_with_first(xjq, books):
    r = xjq("--text-all", "-f", "//title/text() | //author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


# --- Phrase: "A union with mixed result types is written as text results."
# Context: one branch yields elements, another yields text/attributes.

def test_mixed_union_is_written_as_text(xjq, books):
    r = xjq("//book[1]/title | //book[1]/author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Frank Herbert"]


def test_mixed_union_does_not_serialize_xml(xjq, books):
    r = xjq("//title | //author/text()", stdin=books)
    assert r.returncode == 0
    assert "<title>" not in r.stdout


def test_mixed_union_with_attributes(xjq, books):
    r = xjq("//book[1]/@id | //book[1]/title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["b1", "Dune"]


def test_mixed_union_results_are_newline_joined(xjq, books):
    r = xjq("//title | //author/text()", stdin=books)
    assert len(r.stdout.splitlines()) == 6


def test_mixed_union_results_are_normalized(xjq):
    doc = "<doc><a>  spaced   out  </a><b>plain</b></doc>"
    r = xjq("//a | //b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["spaced out", "plain"]


def test_mixed_union_with_first_keeps_one_result(xjq, books):
    r = xjq("-f", "//title | //author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_mixed_union_ignores_json_export(xjq, books):
    r = xjq("-j", "//title | //author/text()", stdin=books)
    assert r.returncode == 0
    assert not r.stdout.startswith("[")


# --- Phrase: "In CSS mode, pass `|` through as CSS query text (no XPath
#             union semantics)." -----------------------------------------
# Context: --css never gives `|` union meaning.

def test_css_pipe_is_not_a_union(xjq, books):
    r = xjq("--css", "title | author", stdin=books)
    assert r.returncode == 1
    assert r.stdout == ""


def test_css_pipe_is_css_namespace_syntax(xjq, books):
    # `*|title` is the CSS any-namespace selector, not a union.
    r = xjq("--css", "*|title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_css_comma_list_still_works(xjq, books):
    r = xjq("--css", "-t", "title, author", stdin=books)
    assert r.returncode == 0
    assert len(r.stdout.splitlines()) == 6


# --- Phrase: "If the CSS engine rejects the selector, report a CSS
#             selector error on stderr with exit code `1`." --------------
# Context: `|` that CSS cannot handle is a selector error, not a union.

def test_css_pipe_selector_exits_one(xjq, books):
    r = xjq("--css", "title | author", stdin=books)
    assert r.returncode == 1


def test_css_pipe_selector_writes_to_stderr(xjq, books):
    r = xjq("--css", "title | author", stdin=books)
    assert r.stderr.strip() != ""


def test_css_pipe_selector_error_mentions_css_or_selector(xjq, books):
    r = xjq("--css", "title | author", stdin=books)
    lowered = r.stderr.lower()
    assert "css" in lowered or "selector" in lowered


def test_css_pipe_selector_error_is_not_a_traceback(xjq, books):
    r = xjq("--css", "title | author", stdin=books)
    assert "Traceback" not in r.stderr


def test_css_pipe_selector_error_is_a_single_line(xjq, books):
    r = xjq("--css", "div.post | p", stdin=books)
    assert len(r.stderr.strip().splitlines()) == 1


def test_css_unknown_namespace_prefix_is_a_selector_error(xjq, books):
    r = xjq("--css", "title|author", stdin=books)
    assert r.returncode == 1
    lowered = r.stderr.lower()
    assert "css" in lowered or "selector" in lowered


def test_css_pipe_error_with_text_flag(xjq, books):
    r = xjq("--css", "-t", "title | author", stdin=books)
    assert r.returncode == 1
    assert r.stdout == ""
