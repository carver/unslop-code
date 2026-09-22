"""XPath `|` union queries, the text flags across them, and CSS pass-through."""

import json

from conftest import BOOKS, MIXED, PAGE

ALL_TEXT = "Dune Frank Herbert Les Miserables Victor Hugo"


# Spec: "Support XPath `|` union in XPath mode." -- both sides contribute their
# matches, in document order.
def test_union_matches_both_sides(run_xjq):
    result = run_xjq("-t", "//title | //author", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Dune\nFrank Herbert\nLes Miserables\nVictor Hugo"


# Spec: "Support XPath `|` union in XPath mode." -- whitespace around the
# operator is optional.
def test_union_without_surrounding_spaces(run_xjq):
    assert run_xjq("-t", "//title|//author", stdin=BOOKS).stdout == run_xjq(
        "-t", "//title | //author", stdin=BOOKS
    ).stdout


# Spec: "Support XPath `|` union in XPath mode." -- more than two sub-paths.
def test_union_of_three_paths(run_xjq):
    result = run_xjq("-t", "//h1 | //p | //missing", stdin=PAGE)
    assert result.stdout == "First\nHello !\nSecond line\nSecond\nSpaced out text"


# Spec: "Support XPath `|` union in XPath mode." -- without a text flag a union
# of elements is XML node output, which shows its first node.
def test_union_of_elements_without_flags_is_node_output(run_xjq):
    result = run_xjq("//author | //title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == "<title>Dune</title>"


# Spec: "Support XPath `|` union in XPath mode." -- a sub-path that matches
# nothing simply adds nothing.
def test_union_with_one_empty_side(run_xjq):
    assert run_xjq("-t", "//missing | //title", stdin=BOOKS).stdout == (
        "Dune\nLes Miserables"
    )


# Spec: "Support XPath `|` union in XPath mode." -- a union matching nothing at
# all writes nothing.
def test_union_matching_nothing_is_silent(run_xjq):
    result = run_xjq("//missing | //absent", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# Spec: "`--text` ... appl[ies] across union queries." -- one line per matched
# element, each holding only that element's direct text (AMBIGUITIES T41).
def test_text_flag_applies_across_a_union(run_xjq):
    assert run_xjq("--text", "//book | //title", stdin=BOOKS).stdout == (
        "Dune\nLes Miserables"
    )


# Spec: "`--text` ... appl[ies] across union queries." -- with `--first`, the
# first line of that output.
def test_text_flag_with_first_across_a_union(run_xjq):
    assert run_xjq("-t", "-f", "//author | //title", stdin=BOOKS).stdout == "Dune"


# Spec: "For XPath union queries with active `--text-all`, concatenate
# descendant text across all union matches into one normalized output string."
def test_text_all_concatenates_across_a_union(run_xjq):
    result = run_xjq("--text-all", "//title | //author", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == ALL_TEXT


# Spec: "... concatenate descendant text across all union matches into one
# normalized output string." -- one string means no newline between matches.
def test_union_text_all_output_is_a_single_line(run_xjq):
    result = run_xjq("--text-all", "//h1 | //p", stdin=PAGE)
    assert "\n" not in result.stdout
    assert result.stdout == "First Post Hello World! Second line Second Spaced out text"


# Spec: "... into one normalized output string." -- the concatenation is
# stripped and its whitespace runs collapsed (AMBIGUITIES T40).
def test_union_text_all_output_is_normalized(run_xjq):
    doc = "<r><a>  one\n\ntwo  </a><b>\tthree </b></r>"
    assert run_xjq("--text-all", "//a | //b", stdin=doc).stdout == "one two three"


# Spec: "For XPath union queries with active `--text-all` ..." -- a non-union
# query keeps one line per element (AMBIGUITIES T39).
def test_non_union_text_all_still_prints_one_line_per_element(run_xjq):
    assert run_xjq("--text-all", "//title", stdin=BOOKS).stdout == (
        "Dune\nLes Miserables"
    )


# Spec: "If `--first` is also active with union + `--text-all`, only the first
# matched union node contributes to the output."
def test_first_limits_the_union_concatenation(run_xjq):
    assert run_xjq("-f", "--text-all", "//title | //author", stdin=BOOKS).stdout == (
        "Dune"
    )


# Spec: "If `--first` is also active with union + `--text-all`, only the first
# matched union node contributes." -- "first" is the first node in document
# order, whichever sub-path it came from.
def test_first_union_node_is_document_order(run_xjq):
    assert run_xjq("-f", "--text-all", "//author | //title", stdin=BOOKS).stdout == (
        "Dune"
    )
    assert run_xjq("-f", "--text-all", "//book | //author", stdin=BOOKS).stdout == (
        "Dune Frank Herbert"
    )


# Spec: "If any union sub-path already performs text extraction, text flags are
# treated as no-op query modifiers." -- a `text()` sub-path.
def test_text_flags_are_no_ops_beside_a_text_sub_path(run_xjq):
    plain = run_xjq("//title/text() | //author", stdin=BOOKS).stdout
    assert run_xjq("--text-all", "//title/text() | //author", stdin=BOOKS).stdout == (
        plain
    )
    assert run_xjq("-t", "//title/text() | //author", stdin=BOOKS).stdout == plain
    assert plain == "Dune\nFrank Herbert\nLes Miserables\nVictor Hugo"


# Spec: "If any union sub-path already performs text extraction, text flags are
# treated as no-op query modifiers." -- an attribute sub-path is text too
# (AMBIGUITIES T42).
def test_text_flags_are_no_ops_beside_an_attribute_sub_path(run_xjq):
    plain = run_xjq("//book/@id | //title", stdin=BOOKS).stdout
    assert run_xjq("--text-all", "//book/@id | //title", stdin=BOOKS).stdout == plain
    assert plain == "b1\nDune\nb2\nLes Miserables"


# Spec: "If any union sub-path already performs text extraction ..." -- when
# every sub-path extracts text the flags are no-ops as well.
def test_text_flags_are_no_ops_when_all_sub_paths_extract_text(run_xjq):
    plain = run_xjq("//title/text() | //author/text()", stdin=BOOKS).stdout
    assert run_xjq("--text-all", "//title/text() | //author/text()", stdin=BOOKS).stdout == plain
    assert plain == "Dune\nFrank Herbert\nLes Miserables\nVictor Hugo"


# Spec: "A union with mixed result types is written as text results." -- each
# element contributes its text rather than a serialization (AMBIGUITIES T43).
def test_mixed_union_is_written_as_text(run_xjq):
    result = run_xjq("//title/text() | //book", stdin=BOOKS)
    assert result.returncode == 0
    assert "<book" not in result.stdout
    assert result.stdout == (
        "Dune Frank Herbert\nDune\nLes Miserables Victor Hugo\nLes Miserables"
    )


# Spec: "A union with mixed result types is written as text results." -- the
# text results are stripped, collapsed and newline-joined like any others.
def test_mixed_union_text_is_normalized(run_xjq):
    doc = "<r><a>  x  y  </a><b id=' q  r '>z</b></r>"
    assert run_xjq("//a | //b/@id", stdin=doc).stdout == "x y\nq r"


# Spec: "A union with mixed result types is written as text results." --
# `--first` keeps the first of those lines.
def test_first_applies_to_a_mixed_union(run_xjq):
    assert run_xjq("-f", "//title/text() | //author", stdin=BOOKS).stdout == "Dune"


# Spec: "Support XPath `|` union in XPath mode." + "`-j`, `--json`: JSON export
# mode for XML element results." (AMBIGUITIES T44)
def test_json_export_of_a_union_of_elements(run_xjq):
    exported = json.loads(run_xjq("-j", "//title | //author", stdin=BOOKS).stdout)
    assert exported == [
        {"title": "Dune"},
        {"author": "Frank Herbert"},
        {"title": "Les Miserables"},
        {"author": "Victor Hugo"},
    ]


# Spec: "`--json` has no effect when results are already auto-detected as text"
# + "A union with mixed result types is written as text results."
def test_json_has_no_effect_on_a_mixed_union(run_xjq):
    plain = run_xjq("//title/text() | //author", stdin=BOOKS).stdout
    assert run_xjq("-j", "//title/text() | //author", stdin=BOOKS).stdout == plain


# Spec: "In CSS mode, pass `|` through as CSS query text (no XPath union
# semantics). If the CSS engine rejects the selector, report a CSS selector
# error on stderr with exit code `1`."
def test_css_mode_rejects_a_union_style_selector(run_xjq):
    result = run_xjq("--css", "h1 | p", stdin=PAGE)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "css" in result.stderr.lower()


# Spec: "In CSS mode, pass `|` through as CSS query text (no XPath union
# semantics)." -- a selector the CSS engine accepts is a namespace selector,
# not a union, and matches nothing here (AMBIGUITIES T45).
def test_css_mode_does_not_give_the_bar_union_semantics(run_xjq):
    result = run_xjq("--css", "h1|p", stdin=PAGE)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "css" in result.stderr.lower()


# Spec: "In CSS mode, pass `|` through as CSS query text ..." -- the text flags
# do not rescue such a selector either.
def test_css_union_selector_fails_with_text_flags_too(run_xjq):
    assert run_xjq("--css", "-t", "h1 | p", stdin=PAGE).returncode == 1
    assert run_xjq("--css", "--text-all", "h1 | p", stdin=PAGE).returncode == 1


# Spec: "In CSS mode, pass `|` through as CSS query text ..." -- the CSS way to
# ask for several selectors, the comma, is unaffected.
def test_css_comma_selector_still_works(run_xjq):
    assert run_xjq("--css", "-t", "h1, p.body", stdin=PAGE).stdout == (
        "First\nHello !\nSecond line\nSecond\nSpaced out text"
    )


# Spec: "`--text` and `--text-all` apply across union queries." -- a `|` inside
# a string literal is not a union operator (AMBIGUITIES T39).
def test_bar_inside_a_string_literal_is_not_a_union(run_xjq):
    doc = "<r><t>a|b</t><t>c|d</t><t>plain</t></r>"
    result = run_xjq("--text-all", "//t[contains(., '|')]", stdin=doc)
    assert result.stdout == "a|b\nc|d"
