"""Spec section: `--compact`.

Compact XML serialization, and the result kinds it deliberately leaves alone.
"""

from conftest import DOC, JSON_OBJECT

FLAT_DOC = '<library><book id="b1"><title>Dune</title></book></library>'


# Phrase: "`-c`, `--compact`: compact output mode."
def test_compact_serializes_a_node_without_added_formatting(xjq):
    result = xjq("--compact", "//book", stdin=FLAT_DOC)
    assert result.returncode == 0
    assert result.stdout == '<book id="b1"><title>Dune</title></book>\n'


# Phrase: "`-c`, `--compact`: compact output mode."
# The short spelling is the same flag.
def test_short_compact_flag(xjq):
    assert xjq("-c", "//book", stdin=FLAT_DOC).stdout == (
        '<book id="b1"><title>Dune</title></book>\n'
    )


# Phrase: "compact XML output has no added pretty-print formatting."
# Without the flag the same node is pretty-printed over several lines.
def test_default_output_is_still_pretty_printed(xjq):
    lines = xjq("//book", stdin=FLAT_DOC).stdout.splitlines()
    assert lines[0] == '<book id="b1">'
    assert lines[1].startswith(" ") and lines[1].strip() == "<title>Dune</title>"
    assert lines[-1] == "</book>"


# Phrase: "compact XML output has no added pretty-print formatting."
def test_compact_output_of_a_flat_node_is_one_line(xjq):
    out = xjq("-c", "/library", stdin=FLAT_DOC).stdout
    assert out.count("\n") == 1
    assert out == FLAT_DOC + "\n"


# Phrase: "`--compact` affects XML serialization only"
def test_compact_does_not_change_text_results(xjq):
    plain = xjq("//title/text()", stdin=DOC).stdout
    assert xjq("-c", "//title/text()", stdin=DOC).stdout == plain
    assert plain == "Dune\nLe Petit Prince\n"


# Phrase: "`--compact` affects XML serialization only"
def test_compact_does_not_change_attribute_results(xjq):
    assert xjq("-c", "//book/@id", stdin=DOC).stdout == "b1\nb2\n"


# Phrase: "`--compact` affects XML serialization only"
# Scalar results keep their XPath string() rendering.
def test_compact_does_not_change_scalar_results(xjq):
    assert xjq("-c", "count(//book)", stdin=DOC).stdout == "2\n"


# Phrase: "For JSON-derived input, `--compact` still applies to resulting XML
#          output."
def test_compact_applies_to_json_derived_nodes(xjq):
    out = xjq("-c", "/root/author", stdin=JSON_OBJECT).stdout
    assert out == (
        '<author type="dict"><first type="str">Frank</first>'
        '<last type="str">Herbert</last></author>\n'
    )


# Phrase: "For JSON-derived input, `--compact` still applies to resulting XML
#          output."
# The pretty default for the same node spans several indented lines.
def test_json_derived_nodes_are_pretty_printed_by_default(xjq):
    lines = xjq("/root/author", stdin=JSON_OBJECT).stdout.splitlines()
    assert lines[0] == '<author type="dict">'
    assert lines[1].strip() == '<first type="str">Frank</first>'
    assert lines[-1] == "</author>"


# Phrase: "`-c`, `--compact`" combined with "`-f`, `--first`".
def test_compact_and_first_combine(xjq):
    assert xjq("-c", "-f", "//book", stdin=FLAT_DOC).stdout == (
        '<book id="b1"><title>Dune</title></book>\n'
    )


# Phrase: "compact XML output" -- a node with no children is self-closing.
def test_compact_output_of_an_empty_element(xjq):
    assert xjq("-c", "//n", stdin='<r><n a="1"/></r>').stdout == '<n a="1"/>\n'
