"""The ``-t``/``--text`` and ``--text-all`` extraction flags."""

from conftest import BOOKS, MIXED, PAGE


# Spec: "`-t`, `--text`: direct text extraction from matched elements, one per
# element."
def test_text_flag_extracts_direct_text(run_xjq):
    result = run_xjq("--text", "//book/title", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLes Miserables"


# Spec: "`-t`, `--text`: direct text extraction ..." -- `-t` is the short form.
def test_text_flag_short_form(run_xjq):
    assert run_xjq("-t", "//book/title", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "`-t`, `--text`: direct text extraction from matched elements, one per
# element." -- an element's own text nodes are joined into a single line, and
# the text of its descendants is left out.
def test_text_flag_is_one_line_per_element(run_xjq):
    assert run_xjq("-t", "//p", stdin=MIXED).stdout == "Hello !"


# Spec: "`-t`, `--text`: direct text extraction ..." -- it replaces the XML node
# output that the same query produces on its own.
def test_text_flag_replaces_node_output(run_xjq):
    assert run_xjq("//book/title", stdin=BOOKS).stdout.rstrip("\n") == "<title>Dune</title>"
    assert run_xjq("-t", "//book/title", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "`-t`, `--text`: direct text extraction ..." -- in CSS mode too.
def test_text_flag_in_css_mode(run_xjq):
    assert run_xjq("--css", "p.body", "-t", stdin=PAGE).stdout == (
        "Hello !\nSecond line\nSpaced out text"
    )


# Spec: "`--text-all`: descendant text extraction from matched elements, one
# per element."
def test_text_all_flag_extracts_descendant_text(run_xjq):
    assert run_xjq("--text-all", "//p", stdin=MIXED).stdout == "Hello World!"


# Spec: "`--text-all`: descendant text extraction from matched elements, one
# per element." -- one line per match, however deep the subtree.
def test_text_all_flag_is_one_line_per_element(run_xjq):
    result = run_xjq("--text-all", "//book", stdin=BOOKS)
    assert result.stdout == "Dune Frank Herbert\nLes Miserables Victor Hugo"


# Spec: "`--text-all`: descendant text extraction ..." -- in CSS mode too.
def test_text_all_flag_in_css_mode(run_xjq):
    assert run_xjq("--css", "#p1", "--text-all", stdin=PAGE).stdout == (
        "First Post Hello World! Second line"
    )


# Spec: "`-t`, `--text`: direct text extraction" vs "`--text-all`: descendant
# text extraction" -- the two differ exactly by the descendants' text.
def test_direct_and_descendant_extraction_differ(run_xjq):
    assert run_xjq("-t", "//h1", stdin=PAGE).stdout == "First\nSecond"
    assert run_xjq("--text-all", "//h1", stdin=PAGE).stdout == "First Post\nSecond"


# Spec: "Multi-match text output joins lines with `\n`."
def test_multi_match_text_is_newline_joined(run_xjq):
    assert run_xjq("-t", "//title", stdin=BOOKS).stdout == "Dune\nLes Miserables"
    assert run_xjq("--css", "title", "-t", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "Multi-match text output joins lines with `\n`." -- a single match is a
# single line with no trailing newline.
def test_single_match_text_has_no_trailing_newline(run_xjq):
    result = run_xjq("-t", "//book[1]/title", stdin=BOOKS)
    assert result.stdout == "Dune"


# Spec: "Strip each result and collapse internal whitespace runs to single
# spaces."
def test_extracted_text_is_stripped_and_collapsed(run_xjq):
    doc = "<r><t>  a\n\n  b\t\tc  </t></r>"
    assert run_xjq("-t", "//t", stdin=doc).stdout == "a b c"
    assert run_xjq("--text-all", "//t", stdin=doc).stdout == "a b c"


# Spec: "Strip each result and collapse internal whitespace runs to single
# spaces." -- the indentation between an element's children collapses to the
# single space that separates their text.
def test_layout_whitespace_collapses_to_one_space(run_xjq):
    assert run_xjq("--text-all", "//book[1]", stdin=BOOKS).stdout == "Dune Frank Herbert"


# Spec: "If both `--text` and `--text-all` are present, `--text-all` wins."
def test_text_all_wins_over_text(run_xjq):
    expected = run_xjq("--text-all", "//p", stdin=MIXED).stdout
    assert run_xjq("-t", "--text-all", "//p", stdin=MIXED).stdout == expected
    assert run_xjq("--text-all", "-t", "//p", stdin=MIXED).stdout == expected
    assert expected == "Hello World!"


# Spec: "If query already extracts text (`text()` or `::text`), `--text` and
# `--text-all` are no-op modifiers." -- an XPath `text()` query.
def test_flags_are_no_ops_for_xpath_text_queries(run_xjq):
    plain = run_xjq("//p/text()", stdin=MIXED).stdout
    assert run_xjq("-t", "//p/text()", stdin=MIXED).stdout == plain
    assert run_xjq("--text-all", "//p/text()", stdin=MIXED).stdout == plain
    assert plain == "Hello\n!"


# Spec: "If query already extracts text (`text()` or `::text`) ..." -- a CSS
# `::text` query keeps its own mode, direct or descendant.
def test_flags_are_no_ops_for_css_text_queries(run_xjq):
    assert run_xjq("--css", "p::text", "--text-all", stdin=MIXED).stdout == "Hello\n!"
    assert run_xjq("--css", "p ::text", "-t", stdin=MIXED).stdout == "Hello\nWorld\n!"


# Spec: "If query already extracts text ..." -- attribute results are text too,
# so the flags leave them alone.
def test_flags_are_no_ops_for_attribute_queries(run_xjq):
    assert run_xjq("-t", "//book/@id", stdin=BOOKS).stdout == "b1\nb2"
    assert run_xjq("--text-all", "//book/@id", stdin=BOOKS).stdout == "b1\nb2"


# Spec: "If query already extracts text ..." -- and scalar results as well.
def test_flags_are_no_ops_for_scalar_results(run_xjq):
    assert run_xjq("-t", "count(//book)", stdin=BOOKS).stdout == "2"
    assert run_xjq("--text-all", "string(//title)", stdin=BOOKS).stdout == "Dune"


# Spec: "`-t`, `--text`: direct text extraction from matched elements" -- an
# element with no direct text of its own contributes no line (AMBIGUITIES T15).
def test_element_without_direct_text_contributes_nothing(run_xjq):
    result = run_xjq("-t", "//book", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == ""


# Spec: "`-t`, `--text`: direct text extraction from matched elements" -- a
# query matching nothing still exits successfully with no output.
def test_text_flag_without_matches(run_xjq):
    result = run_xjq("-t", "//missing", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
