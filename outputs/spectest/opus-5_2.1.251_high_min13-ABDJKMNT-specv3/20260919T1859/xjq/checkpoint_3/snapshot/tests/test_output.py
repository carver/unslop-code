"""Output formatting: text/attribute results, XML node results, and no-match."""

from conftest import BOOKS

SPACED = "<r><t>  leading and trailing  </t><t>inner\n\tgaps   here</t></r>"


# Spec: "Text/attribute results: strip each result"
def test_text_results_are_stripped(run_xjq):
    result = run_xjq("//t[1]/text()", stdin=SPACED)
    assert result.stdout == "leading and trailing"


# Spec: "Text/attribute results: strip each result" -- attributes too.
def test_attribute_results_are_stripped(run_xjq):
    result = run_xjq("//t/@name", stdin='<r><t name="  padded  "/></r>')
    assert result.stdout == "padded"


# Spec: "collapse internal whitespace runs to single spaces"
def test_internal_whitespace_is_collapsed(run_xjq):
    result = run_xjq("//t[2]/text()", stdin=SPACED)
    assert result.stdout == "inner gaps here"


# Spec: "collapse internal whitespace runs to single spaces" -- newlines and
# tabs count as whitespace and collapse along with spaces.
def test_newlines_and_tabs_collapse(run_xjq):
    doc = "<r><t>a\n\n  b\t\tc</t></r>"
    assert run_xjq("//t/text()", stdin=doc).stdout == "a b c"


# Spec: "collapse internal whitespace runs to single spaces" -- attribute values.
def test_attribute_whitespace_is_collapsed(run_xjq):
    result = run_xjq("//t/@name", stdin='<r><t name="a   b"/></r>')
    assert result.stdout == "a b"


# Spec: "then join results with each on a newline"
def test_multiple_text_results_are_newline_joined(run_xjq):
    result = run_xjq("//title/text()", stdin=BOOKS)
    assert result.stdout == "Dune\nLes Miserables"


# Spec: "then join results with each on a newline" -- multiple attributes.
def test_multiple_attribute_results_are_newline_joined(run_xjq):
    result = run_xjq("//book/@id", stdin=BOOKS)
    assert result.stdout == "b1\nb2"


# Spec: "No trailing newline."
def test_no_trailing_newline_on_text_results(run_xjq):
    assert not run_xjq("//title/text()", stdin=BOOKS).stdout.endswith("\n")
    assert not run_xjq("//book[1]/@id", stdin=BOOKS).stdout.endswith("\n")


# Spec: "XML node results: pretty-print serialized XML"
def test_element_result_is_serialized(run_xjq):
    result = run_xjq("//book[1]", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout.startswith('<book id="b1" lang="en">')
    assert "<title>Dune</title>" in result.stdout
    assert "Les Miserables" not in result.stdout


# Spec: "XML node results: pretty-print serialized XML" -- nested children are
# indented onto their own lines (see AMBIGUITIES T4: indentation is normalized).
def test_element_result_is_pretty_printed(run_xjq):
    result = run_xjq("//book[2]", stdin=BOOKS)
    lines = result.stdout.rstrip("\n").split("\n")
    assert lines[0] == '<book id="b2" lang="fr">'
    assert lines[1] == "  <title>Les Miserables</title>"
    assert lines[2] == "  <author>Victor Hugo</author>"
    assert lines[3] == "</book>"


# Spec: "XML node results: pretty-print serialized XML" -- input without any
# whitespace is expanded.
def test_compact_input_is_expanded(run_xjq):
    result = run_xjq("/a", stdin="<a><b>x</b></a>")
    assert result.stdout.rstrip("\n") == "<a>\n  <b>x</b>\n</a>"


# Spec: "XML node results: pretty-print serialized XML" -- the whole document.
def test_root_node_result(run_xjq):
    result = run_xjq("/library", stdin=BOOKS)
    assert result.stdout.startswith("<library>")
    assert result.stdout.rstrip("\n").endswith("</library>")


# Spec: "when multiple XML nodes match, output only the first node."
def test_only_first_node_of_many(run_xjq):
    result = run_xjq("//book", stdin=BOOKS)
    assert "Dune" in result.stdout
    assert "Les Miserables" not in result.stdout
    assert result.stdout.count("<book") == 1


# Spec: "when multiple XML nodes match, output only the first node." -- "first"
# is document order, as produced by the XPath engine.
def test_first_node_is_document_order(run_xjq):
    result = run_xjq("//title", stdin=BOOKS)
    assert result.stdout.rstrip("\n") == "<title>Dune</title>"


# Spec: "No-match output: write nothing to stdout/stderr."
def test_no_match_writes_nothing(run_xjq):
    result = run_xjq("//missing", stdin=BOOKS)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "No-match output: write nothing to stdout/stderr." -- also for text and
# attribute queries that select nothing.
def test_no_match_text_and_attribute_queries(run_xjq):
    assert run_xjq("//missing/text()", stdin=BOOKS).stdout == ""
    assert run_xjq("//book/@missing", stdin=BOOKS).stdout == ""


# Spec: "Text/attribute results ..." -- scalar XPath results are text results;
# XPath 1.0 renders an integral number without a decimal point (AMBIGUITIES T2).
def test_scalar_results_are_rendered_as_text(run_xjq):
    assert run_xjq("count(//book)", stdin=BOOKS).stdout == "2"
    assert run_xjq("count(//book) + 0.5", stdin=BOOKS).stdout == "2.5"
    assert run_xjq("boolean(//book)", stdin=BOOKS).stdout == "true"
    assert run_xjq("boolean(//missing)", stdin=BOOKS).stdout == "false"
    assert run_xjq("string(//book[1]/@id)", stdin=BOOKS).stdout == "b1"
