"""Spec sections: the `--text` / `--text-all` CLI additions, Text Extraction,
and Flag Rules.

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


# --- Phrase: "`-t`, `--text`: direct text extraction from matched elements,
#             one per element." --------------------------------------------
# Context: both spellings of the flag; the element's own text nodes only.

def test_text_long_flag_extracts_direct_text(xjq, books):
    r = xjq("--text", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_text_short_flag_extracts_direct_text(xjq, books):
    r = xjq("-t", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_short_and_long_flag_agree(xjq, books):
    short = xjq("-t", "//author", stdin=books)
    long = xjq("--text", "//author", stdin=books)
    assert short.stdout == long.stdout


def test_text_excludes_descendant_element_text(xjq, mixed):
    r = xjq("-t", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello world"
    assert "bold" not in r.stdout


def test_text_is_one_line_per_matched_element(xjq, page):
    r = xjq("-t", "//h2", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First", "Second"]


def test_text_of_element_with_only_whitespace_text(xjq, books):
    r = xjq("-t", "//book", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_text_flag_works_with_css_flag(xjq, books):
    r = xjq("--css", "-t", "title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_text_flag_replaces_xml_node_output(xjq, books):
    r = xjq("-t", "//title", stdin=books)
    assert r.returncode == 0
    assert "<title>" not in r.stdout


def test_text_flag_with_no_match_writes_nothing(xjq, books):
    r = xjq("-t", "//nosuch", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


# --- Phrase: "`--text-all`: descendant text extraction from matched
#             elements, one per element." ---------------------------------
# Context: the whole subtree's text, still collapsed to a single line per
# matched element.

def test_text_all_extracts_descendant_text(xjq, mixed):
    r = xjq("--text-all", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello bold world"


def test_text_all_is_one_line_per_matched_element(xjq, books):
    # Ambiguity T14: the subtree's text nodes are concatenated (string-value)
    # and then collapsed, producing exactly one line per <book>.
    r = xjq("--text-all", "//book", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Dune Frank Herbert 1965",
        "Le Petit Prince Antoine de Saint-Exupery 1943",
        "Neuromancer William Gibson 1984",
    ]


def test_text_all_on_leaf_elements_matches_direct_text(xjq, books):
    r = xjq("--text-all", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_text_all_works_with_css_flag(xjq, page):
    r = xjq("--css", "--text-all", "div.post", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "First Hello bold world",
        "Second Bye",
    ]


def test_text_all_with_no_match_writes_nothing(xjq, books):
    r = xjq("--text-all", "//nosuch", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


def test_text_all_differs_from_text(xjq, mixed):
    direct = xjq("-t", "//p", stdin=mixed)
    every = xjq("--text-all", "//p", stdin=mixed)
    assert direct.stdout == "Hello world"
    assert every.stdout == "Hello bold world"


# --- Phrase: "Multi-match text output joins lines with `\n`." -------------
# Context: several extracted results are newline separated.

def test_multi_match_text_joined_with_newline(xjq, books):
    r = xjq("-t", "//author", stdin=books)
    assert r.returncode == 0
    assert r.stdout == (
        "Frank Herbert\nAntoine de Saint-Exupery\nWilliam Gibson"
    )


def test_multi_match_text_all_joined_with_newline(xjq, page):
    r = xjq("--text-all", "//div", stdin=page)
    assert r.returncode == 0
    assert r.stdout == "First Hello bold world\nSecond Bye"


def test_multi_match_css_text_joined_with_newline(xjq, books):
    r = xjq("--css", "year::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "1965\n1943\n1984"


def test_multi_match_text_has_no_trailing_newline(xjq, books):
    r = xjq("-t", "//title", stdin=books)
    assert r.returncode == 0
    assert not r.stdout.endswith("\n")


def test_single_match_text_has_no_separator(xjq, books):
    r = xjq("-t", "//book[1]/title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"
    assert "\n" not in r.stdout


def test_text_results_keep_document_order(xjq, books):
    r = xjq("-t", "//year", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1965", "1943", "1984"]


# --- Phrase: "Strip each result" ------------------------------------------
# Context: leading/trailing whitespace of each extracted line is removed.

def test_extracted_text_is_stripped(xjq):
    r = xjq("-t", "//b", stdin="<a><b>   padded   </b></a>")
    assert r.returncode == 0
    assert r.stdout == "padded"


def test_extracted_text_strips_newlines_and_tabs(xjq):
    r = xjq("-t", "//b", stdin="<a><b>\n\t value \t\n</b></a>")
    assert r.returncode == 0
    assert r.stdout == "value"


def test_each_extracted_result_is_stripped_independently(xjq):
    doc = "<a><b>  one  </b><b>\ttwo\t</b></a>"
    r = xjq("-t", "//b", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["one", "two"]


def test_css_text_result_is_stripped(xjq):
    r = xjq("--css", "b::text", stdin="<a><b>  padded  </b></a>")
    assert r.returncode == 0
    assert r.stdout == "padded"


def test_descendant_text_nodes_are_stripped_individually(xjq):
    doc = "<a><p>  one  <b>  two  </b>  three  </p></a>"
    r = xjq("--css", "p ::text", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["one", "two", "three"]


def test_text_all_result_is_stripped(xjq):
    r = xjq("--text-all", "//p", stdin="<a><p>  <b> x </b>  </p></a>")
    assert r.returncode == 0
    assert r.stdout == "x"


# --- Phrase: "collapse internal whitespace runs to single spaces" ---------
# Context: whitespace inside an extracted result is normalized.

def test_extracted_text_collapses_internal_runs(xjq):
    r = xjq("-t", "//b", stdin="<a><b>two    words</b></a>")
    assert r.returncode == 0
    assert r.stdout == "two words"


def test_extracted_text_collapses_internal_newlines(xjq):
    r = xjq("-t", "//b", stdin="<a><b>line one\nline two</b></a>")
    assert r.returncode == 0
    assert r.stdout == "line one line two"


def test_direct_text_across_a_child_collapses(xjq):
    # The two direct text nodes "a " and " b" concatenate to "a  b".
    r = xjq("-t", "//p", stdin="<a><p>a <i>skip</i> b</p></a>")
    assert r.returncode == 0
    assert r.stdout == "a b"


def test_text_all_collapses_indentation_between_children(xjq, books):
    r = xjq("--text-all", "//book[1]", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune Frank Herbert 1965"
    assert "  " not in r.stdout


def test_css_text_collapses_internal_whitespace(xjq):
    r = xjq("--css", "b::text", stdin="<a><b>a \t\n\r  b</b></a>")
    assert r.returncode == 0
    assert r.stdout == "a b"


def test_single_spaces_are_left_alone_when_extracting(xjq):
    r = xjq("-t", "//b", stdin="<a><b>already clean text</b></a>")
    assert r.returncode == 0
    assert r.stdout == "already clean text"


# --- Phrase: "If both `--text` and `--text-all` are present, `--text-all`
#             wins." ------------------------------------------------------
# Context: the two flags are not additive; --text-all takes precedence.

def test_text_all_wins_over_text(xjq, mixed):
    r = xjq("-t", "--text-all", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello bold world"


def test_text_all_wins_regardless_of_flag_order(xjq, mixed):
    first = xjq("-t", "--text-all", "//p", stdin=mixed)
    second = xjq("--text-all", "-t", "//p", stdin=mixed)
    assert first.stdout == second.stdout == "Hello bold world"


def test_text_all_wins_with_long_text_flag(xjq, mixed):
    r = xjq("--text", "--text-all", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello bold world"


def test_text_all_wins_in_css_mode(xjq, page):
    r = xjq("--css", "-t", "--text-all", "div.post", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First Hello bold world", "Second Bye"]


def test_both_flags_match_text_all_alone(xjq, books):
    both = xjq("-t", "--text-all", "//book", stdin=books)
    alone = xjq("--text-all", "//book", stdin=books)
    assert both.stdout == alone.stdout


# --- Phrase: "If query already extracts text (`text()` or `::text`),
#             `--text` and `--text-all` are no-op modifiers." --------------
# Context: the flags never re-process a result that is already text.

def test_text_flag_is_a_noop_for_an_xpath_text_query(xjq, books):
    plain = xjq("//title/text()", stdin=books)
    flagged = xjq("-t", "//title/text()", stdin=books)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_text_all_flag_is_a_noop_for_an_xpath_text_query(xjq, books):
    plain = xjq("//title/text()", stdin=books)
    flagged = xjq("--text-all", "//title/text()", stdin=books)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout


def test_text_all_does_not_expand_an_xpath_text_query(xjq, mixed):
    # //p/text() already yields the direct text nodes; --text-all must not
    # turn them into the subtree's text.
    r = xjq("--text-all", "//p/text()", stdin=mixed)
    assert r.returncode == 0
    assert "bold" not in r.stdout


def test_text_flag_is_a_noop_for_a_css_direct_text_query(xjq, books):
    plain = xjq("--css", "title::text", stdin=books)
    flagged = xjq("--css", "-t", "title::text", stdin=books)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_text_all_flag_is_a_noop_for_a_css_direct_text_query(xjq, mixed):
    plain = xjq("--css", "p::text", stdin=mixed)
    flagged = xjq("--css", "--text-all", "p::text", stdin=mixed)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout == "Hello world"


def test_text_flag_is_a_noop_for_a_css_descendant_text_query(xjq, mixed):
    plain = xjq("--css", "p ::text", stdin=mixed)
    flagged = xjq("--css", "-t", "p ::text", stdin=mixed)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout == "Hello\nbold\nworld"


def test_text_all_flag_is_a_noop_for_a_css_descendant_text_query(xjq, mixed):
    plain = xjq("--css", "p ::text", stdin=mixed)
    flagged = xjq("--css", "--text-all", "p ::text", stdin=mixed)
    assert flagged.returncode == 0
    assert flagged.stdout == plain.stdout


def test_both_flags_are_a_noop_for_a_css_text_query(xjq, mixed):
    plain = xjq("--css", "p::text", stdin=mixed)
    flagged = xjq("--css", "-t", "--text-all", "p::text", stdin=mixed)
    assert flagged.stdout == plain.stdout == "Hello world"


def test_text_flag_is_a_noop_for_attribute_results(xjq, books):
    # Ambiguity T18: "already extracts text" is decided from the result kind,
    # and attribute results are already text.
    r = xjq("-t", "//book/@id", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "b1\nb2\nb3"


def test_text_flag_is_a_noop_for_a_string_function_result(xjq, books):
    r = xjq("-t", "string(//book[1]/title)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


# --- Phrase: flags remain compatible with the rest of the CLI -------------
# Context: the new options coexist with the QUERY/INFILE positionals.

def test_text_flag_with_infile_positional(xjq, books):
    r = xjq("-t", "//title", "ignored.xml", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


def test_help_lists_the_new_options(xjq):
    r = xjq("--help", stdin="")
    assert r.returncode == 0
    assert "--css" in r.stdout
    assert "--text-all" in r.stdout
    assert "--text" in r.stdout


def test_text_flag_still_reports_xml_parse_errors(xjq):
    r = xjq("-t", "//a", stdin="<a><b></a>")
    assert r.returncode == 1
    lowered = r.stderr.lower()
    assert "xml" in lowered or "parse" in lowered


def test_text_flag_still_reports_xpath_errors(xjq, books):
    r = xjq("-t", "//[", stdin=books)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()
