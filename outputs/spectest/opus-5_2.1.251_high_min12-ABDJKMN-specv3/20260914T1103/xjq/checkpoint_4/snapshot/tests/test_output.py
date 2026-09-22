"""Spec section: Output.

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


# --- Phrase: "Text/attribute results: strip each result" ------------------
# Context: leading/trailing whitespace is removed from every result.

def test_text_result_is_stripped(xjq):
    r = xjq("//b/text()", stdin="<a><b>   padded   </b></a>")
    assert r.returncode == 0
    assert r.stdout == "padded"


def test_text_result_strips_newlines_and_tabs(xjq):
    r = xjq("//b/text()", stdin="<a><b>\n\t  value \t\n</b></a>")
    assert r.returncode == 0
    assert r.stdout == "value"


def test_attribute_result_is_stripped(xjq):
    r = xjq("//b/@v", stdin='<a><b v="  spaced  "/></a>')
    assert r.returncode == 0
    assert r.stdout == "spaced"


def test_each_result_is_stripped_independently(xjq):
    doc = "<a><b>  one  </b><b>\ttwo\t</b><b>\nthree\n</b></a>"
    r = xjq("//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["one", "two", "three"]


def test_string_function_result_is_stripped(xjq):
    r = xjq("string(//b)", stdin="<a><b>  padded  </b></a>")
    assert r.returncode == 0
    assert r.stdout == "padded"


# --- Phrase: "collapse internal whitespace runs to single spaces" ---------
# Context: whitespace inside a result is normalized.

def test_internal_double_space_collapses(xjq):
    r = xjq("//b/text()", stdin="<a><b>two    words</b></a>")
    assert r.returncode == 0
    assert r.stdout == "two words"


def test_internal_newlines_collapse_to_single_space(xjq):
    r = xjq("//b/text()", stdin="<a><b>line one\nline two</b></a>")
    assert r.returncode == 0
    assert r.stdout == "line one line two"


def test_internal_mixed_whitespace_collapses(xjq):
    r = xjq("//b/text()", stdin="<a><b>a \t\n\r  b</b></a>")
    assert r.returncode == 0
    assert r.stdout == "a b"


def test_strip_and_collapse_combined(xjq):
    r = xjq("//b/text()", stdin="<a><b>\n   many   \n  spaces   here \n</b></a>")
    assert r.returncode == 0
    assert r.stdout == "many spaces here"


def test_attribute_internal_whitespace_collapses(xjq):
    r = xjq("//b/@class", stdin='<a><b class="one   two\tthree"/></a>')
    assert r.returncode == 0
    assert r.stdout == "one two three"


def test_single_spaces_are_left_alone(xjq):
    r = xjq("//b/text()", stdin="<a><b>already clean text</b></a>")
    assert r.returncode == 0
    assert r.stdout == "already clean text"


def test_string_value_of_element_with_nested_markup_is_collapsed(xjq):
    doc = "<a><b>\n  <c>one</c>\n  <c>two</c>\n</b></a>"
    r = xjq("string(//b)", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "one two"


# --- Phrase: "then join results with each on a newline" -------------------
# Context: multiple text/attribute results are newline separated.

def test_multiple_text_results_joined_by_newline(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune\nLe Petit Prince\nNeuromancer"


def test_multiple_attribute_results_joined_by_newline(xjq, books):
    r = xjq("//book/@lang", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "en\nfr\nen"


def test_results_keep_document_order(xjq, books):
    r = xjq("//year/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1965", "1943", "1984"]


def test_single_result_has_no_separator(xjq, books):
    r = xjq("//book[1]/title/text()", stdin=books)
    assert r.returncode == 0
    assert "\n" not in r.stdout


# --- Phrase: "No trailing newline." ---------------------------------------
# Context: stdout ends with the last character of the last result.

def test_single_text_result_has_no_trailing_newline(xjq):
    r = xjq("//b/text()", stdin="<a><b>only</b></a>")
    assert r.returncode == 0
    assert r.stdout == "only"
    assert not r.stdout.endswith("\n")


def test_multiple_text_results_have_no_trailing_newline(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0
    assert not r.stdout.endswith("\n")


def test_attribute_result_has_no_trailing_newline(xjq, books):
    r = xjq("//library/@name", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "City Central"


# --- Phrase: "XML node results: pretty-print serialized XML" --------------
# Context: selecting an element prints XML, not its string value.

def test_element_result_is_serialized_as_xml(xjq):
    r = xjq("//b", stdin="<a><b>text</b></a>")
    assert r.returncode == 0
    assert r.stdout.strip() == "<b>text</b>"


def test_element_result_includes_attributes(xjq):
    r = xjq("//b", stdin='<a><b id="x">text</b></a>')
    assert r.returncode == 0
    assert '<b id="x">text</b>' in r.stdout


def test_element_result_includes_children(xjq):
    r = xjq("//book[1]", stdin="<lib><book><t>Dune</t></book></lib>")
    assert r.returncode == 0
    out = r.stdout
    assert "<book>" in out
    assert "<t>Dune</t>" in out
    assert "</book>" in out


def test_nested_element_is_indented(xjq):
    # Ambiguity T7: a single-line input is re-indented on output.
    r = xjq("/a", stdin="<a><b><c>deep</c></b></a>")
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 4
    assert lines[0].strip() == "<a>"
    # Each level is indented further than its parent.
    indents = [len(ln) - len(ln.lstrip()) for ln in lines[:3]]
    assert indents[0] < indents[1] < indents[2]


def test_pretty_printed_output_reparses_to_same_content(xjq):
    doc = "<a><b id='1'>x</b><b id='2'>y</b></a>"
    r = xjq("/a", stdin=doc)
    assert r.returncode == 0
    r2 = xjq("//b/@id", stdin=r.stdout)
    assert r2.returncode == 0
    assert r2.stdout.splitlines() == ["1", "2"]


def test_root_element_result(xjq, books):
    r = xjq("/library", stdin=books)
    assert r.returncode == 0
    assert r.stdout.lstrip().startswith("<library")
    assert r.stdout.rstrip().endswith("</library>")


def test_empty_element_is_serialized(xjq):
    r = xjq("//b", stdin="<a><b/></a>")
    assert r.returncode == 0
    assert r.stdout.strip() in ("<b/>", "<b></b>")


def test_element_result_does_not_include_tail_text(xjq):
    r = xjq("//b", stdin="<a><b>inner</b>TAILTEXT</a>")
    assert r.returncode == 0
    assert "TAILTEXT" not in r.stdout


def test_xml_output_has_no_trailing_newline(xjq):
    # Ambiguity T6: the "no trailing newline" rule is applied to XML output too.
    r = xjq("//b", stdin="<a><b>text</b></a>")
    assert r.returncode == 0
    assert not r.stdout.endswith("\n")


def test_mixed_content_is_preserved(xjq):
    # Ambiguity T7: only whitespace-only text is re-indented.
    r = xjq("//p", stdin="<a><p>lead <b>bold</b> tail</p></a>")
    assert r.returncode == 0
    assert "lead " in r.stdout
    assert " tail" in r.stdout


def test_comment_node_result_is_serialized(xjq):
    # Ambiguity T10: comments take the XML branch.
    r = xjq("//comment()", stdin="<a><!-- note --><b/></a>")
    assert r.returncode == 0
    assert "note" in r.stdout


# --- Phrase: "when multiple XML nodes match, output only the first node" --
# Context: a node-set of elements is summarized by its first member.

def test_only_first_element_is_printed(xjq, books):
    r = xjq("//book", stdin=books)
    assert r.returncode == 0
    assert 'id="b1"' in r.stdout
    assert 'id="b2"' not in r.stdout
    assert 'id="b3"' not in r.stdout


def test_first_node_is_document_order_first(xjq):
    doc = "<a><b>first</b><b>second</b><b>third</b></a>"
    r = xjq("//b", stdin=doc)
    assert r.returncode == 0
    assert "first" in r.stdout
    assert "second" not in r.stdout


def test_first_node_of_union_result(xjq, books):
    r = xjq("//author | //title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.count("<title>") + r.stdout.count("<author>") == 1


def test_single_element_match_prints_that_element(xjq, books):
    r = xjq("//book[@lang='fr']", stdin=books)
    assert r.returncode == 0
    assert "Le Petit Prince" in r.stdout
    assert "Dune" not in r.stdout


# --- Phrase: "No-match output: write nothing to stdout/stderr." -----------
# Context: an empty result set produces completely empty output.

def test_no_match_writes_nothing_to_stdout(xjq, books):
    r = xjq("//nonexistent", stdin=books)
    assert r.stdout == ""


def test_no_match_writes_nothing_to_stderr(xjq, books):
    r = xjq("//nonexistent", stdin=books)
    assert r.stderr == ""


def test_no_match_text_query_writes_nothing(xjq, books):
    r = xjq("//nonexistent/text()", stdin=books)
    assert r.stdout == ""
    assert r.stderr == ""


def test_no_match_attribute_query_writes_nothing(xjq, books):
    r = xjq("//book/@missing", stdin=books)
    assert r.stdout == ""
    assert r.stderr == ""


def test_no_match_writes_not_even_a_newline(xjq, books):
    r = xjq("//nope", stdin=books)
    assert r.stdout == ""
    assert len(r.stdout) == 0


def test_empty_string_result_writes_nothing(xjq, books):
    r = xjq("string(//nope)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_whitespace_only_text_nodes_produce_no_output(xjq, books):
    # Ambiguity T5: results empty after cleaning are dropped, not kept as
    # blank lines.
    r = xjq("/library/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


# --- Phrase: scalar results (ambiguities T3, T4) --------------------------
# Context: "Evaluate QUERY with XPath 1.0" + the text output rule; the spec
# does not state how numbers/booleans render.

def test_count_renders_as_xpath_1_0_integer(xjq, books):
    # Ambiguity T3: chosen rendering is "3", not "3.0".
    r = xjq("count(//book)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "3"


def test_non_integral_number_keeps_fraction(xjq):
    r = xjq("3 div 2", stdin="<a/>")
    assert r.returncode == 0
    assert r.stdout == "1.5"


def test_boolean_true_renders_lowercase(xjq, books):
    # Ambiguity T4: chosen rendering is XPath 1.0 "true"/"false".
    r = xjq("count(//book) > 1", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "true"


def test_boolean_false_renders_lowercase(xjq, books):
    r = xjq("count(//book) > 99", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "false"
