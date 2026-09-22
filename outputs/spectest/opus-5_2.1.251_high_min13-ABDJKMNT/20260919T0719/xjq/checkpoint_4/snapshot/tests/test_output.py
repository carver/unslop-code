"""Spec section: Output.

Text/attribute normalization, XML node pretty-printing, and the silent
no-match case.
"""

from conftest import DOC, HTMLISH_DOC


# Phrase: "Text/attribute results: ... join results with each on a newline."
def test_text_results_are_newline_separated(xjq):
    result = xjq("//title/text()", stdin=DOC)
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "Text/attribute results: ... join results with each on a newline."
def test_attribute_results_are_newline_separated(xjq):
    result = xjq("//book/@id", stdin=DOC)
    assert result.stdout == "b1\nb2\n"


# Phrase: "Text/attribute results: strip each result"
def test_each_result_is_stripped(xjq):
    doc = "<r><v>  padded  </v><v>\n\ttabbed\n</v></r>"
    result = xjq("//v/text()", stdin=doc)
    assert result.stdout == "padded\ntabbed\n"


# Phrase: "collapse internal whitespace runs to single spaces"
def test_internal_whitespace_runs_collapse_to_single_spaces(xjq):
    doc = "<r><v>one   two\t\tthree</v></r>"
    result = xjq("//v/text()", stdin=doc)
    assert result.stdout == "one two three\n"


# Phrase: "collapse internal whitespace runs to single spaces"
# Newlines inside a single result become spaces, not extra lines.
def test_internal_newlines_collapse_to_spaces(xjq):
    doc = "<r><v>first\n    second\n    third</v></r>"
    result = xjq("//v/text()", stdin=doc)
    assert result.stdout == "first second third\n"


# Phrase: "strip each result, collapse internal whitespace runs"
def test_attribute_values_are_normalized_too(xjq):
    doc = '<r><n label="  spaced   out  "/></r>'
    result = xjq("//n/@label", stdin=doc)
    assert result.stdout == "spaced out\n"


# Phrase: "Text/attribute results" applied to an html-shaped document.
def test_normalizes_text_from_html_shaped_input(xjq):
    result = xjq("//p/text()", stdin=HTMLISH_DOC)
    assert result.stdout == "Hello world\n"


# Phrase: "XML node results: pretty-print serialized XML"
def test_single_element_match_is_pretty_printed(xjq):
    doc = "<library><book id=\"b1\"><title>Dune</title></book></library>"
    result = xjq("//book", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.startswith('<book id="b1">')
    assert "<title>Dune</title>" in result.stdout
    assert result.stdout.endswith("\n")


# Phrase: "XML node results: pretty-print serialized XML"
# Nested children appear on their own indented lines.
def test_pretty_printed_output_is_indented(xjq):
    doc = "<library><book><title>Dune</title><author>Frank</author></book></library>"
    lines = xjq("//book", stdin=doc).stdout.splitlines()
    assert lines[0] == "<book>"
    assert lines[1].startswith(" ") and lines[1].strip() == "<title>Dune</title>"
    assert lines[2].startswith(" ") and lines[2].strip() == "<author>Frank</author>"
    assert lines[-1] == "</book>"


# Phrase: "XML node results: pretty-print serialized XML"
# Attributes and self-closing elements survive serialization.
def test_serialization_preserves_attributes(xjq):
    doc = '<r><n a="1" b="2"/></r>'
    out = xjq("//n", stdin=doc).stdout
    assert 'a="1"' in out and 'b="2"' in out


# Phrase: "when multiple XML nodes match, output only the first node"
def test_only_the_first_of_multiple_nodes_is_printed(xjq):
    out = xjq("//book", stdin=DOC).stdout
    assert "Dune" in out
    assert "Le Petit Prince" not in out


# Phrase: "when multiple XML nodes match, output only the first node"
# "First" is document order.
def test_first_node_is_in_document_order(xjq):
    doc = "<r><n>alpha</n><n>beta</n><n>gamma</n></r>"
    out = xjq("//n", stdin=doc).stdout
    assert "alpha" in out
    assert "beta" not in out and "gamma" not in out


# Phrase: "XML node results" -- the document element itself is serializable.
def test_root_element_query(xjq):
    out = xjq("/library", stdin=DOC).stdout
    assert out.startswith("<library>")
    assert "Dune" in out and "Le Petit Prince" in out


# Phrase: "No-match output: write nothing to stdout/stderr."
def test_no_match_writes_nothing(xjq):
    result = xjq("//nonexistent", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Phrase: "No-match output: write nothing to stdout/stderr."
def test_no_match_on_attribute_query_writes_nothing(xjq):
    result = xjq("//book/@missing", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""


# Phrase: "No-match output: write nothing to stdout/stderr."
# A predicate that filters everything out is still a clean no-match.
def test_empty_predicate_result_writes_nothing(xjq):
    result = xjq("//book[@lang='de']/title/text()", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0
