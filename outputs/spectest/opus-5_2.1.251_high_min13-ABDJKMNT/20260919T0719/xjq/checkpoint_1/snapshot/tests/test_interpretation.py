"""Interpretation choices recorded in AMBIGUITIES.md.

Each section names the ambiguity entry it pins down.
"""

from conftest import DOC


# T3: scalar (number/boolean) results are rendered with XPath 1.0 string()
# conversion rules, then treated like any other text result.
def test_number_result_uses_xpath_string_conversion(xjq):
    assert xjq("count(//book)", stdin=DOC).stdout == "2\n"


# T3: non-integral numbers keep their fractional part.
def test_fractional_number_result(xjq):
    assert xjq("count(//book) div 4", stdin=DOC).stdout == "0.5\n"


# T3: booleans render as "true"/"false".
def test_boolean_results(xjq):
    assert xjq("count(//book) > 1", stdin=DOC).stdout == "true\n"
    assert xjq("count(//book) > 9", stdin=DOC).stdout == "false\n"


# T4: results that are empty after normalization are dropped, so
# whitespace-only text nodes never produce blank lines.
def test_whitespace_only_text_nodes_are_dropped(xjq):
    result = xjq("/library/text()", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# T4: real text is kept even when whitespace-only siblings are dropped.
def test_mixed_text_nodes_keep_only_non_empty_results(xjq):
    doc = "<r>\n  <v>alpha</v>\n  <v>beta</v>\n</r>"
    assert xjq("//text()", stdin=doc).stdout == "alpha\nbeta\n"


# T8: an empty-string scalar is a no-match, so nothing is written.
def test_empty_string_result_writes_nothing(xjq):
    result = xjq("string(//missing)", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# T6: output ends with a single trailing newline.
def test_output_ends_with_single_newline(xjq):
    assert xjq("//book/@id", stdin=DOC).stdout == "b1\nb2\n"
    assert xjq("(//title)[1]/text()", stdin=DOC).stdout.count("\n") == 1


# T7: the kind of the first result decides the rendering mode; an element
# first result means XML output even if later results are strings.
def test_first_result_kind_selects_rendering_mode(xjq):
    out = xjq("//book[1] | //book[2]/@id", stdin=DOC).stdout
    assert out.startswith('<book id="b1"')
    assert "b2" not in out


# T5: serialized XML is re-indented, so compact input comes out pretty.
def test_compact_input_is_reindented(xjq):
    doc = "<r><a><b>x</b></a></r>"
    assert xjq("//a", stdin=doc).stdout == "<a>\n  <b>x</b>\n</a>\n"


# T5: a node's tail text is not part of its serialization.
def test_tail_text_is_not_serialized(xjq):
    doc = "<r><a>x</a>tail-text</r>"
    assert xjq("//a", stdin=doc).stdout == "<a>x</a>\n"


# T2: input that is not well-formed XML is an error even when it looks
# like HTML (no lenient HTML recovery mode).
def test_non_well_formed_html_is_a_parse_error(xjq):
    result = xjq("//p", stdin="<html><body><p>hi<br></body></html>")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# T9: when the input cannot be parsed, the parse error is reported even if
# the query is also invalid.
def test_parse_error_takes_precedence_over_xpath_error(xjq):
    result = xjq("//book[", stdin="<a>")
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message
