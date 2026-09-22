"""Rendering of query results.

Spec section: "## Output"
"""

import textwrap


# Spec: "Text/attribute results: strip each result"
# Context: leading and trailing whitespace around a text node is removed.
def test_text_result_is_stripped(run_xjq):
    result = run_xjq("//a/text()", stdin="<r><a>   padded   </a></r>")
    assert result.stdout == "padded\n"


# Spec: "Text/attribute results: strip each result"
# Context: attribute values are handled by the same text path.
def test_attribute_result_is_stripped(run_xjq):
    result = run_xjq("//a/@v", stdin="<r><a v='  spaced  '/></r>")
    assert result.stdout == "spaced\n"


# Spec: "collapse internal whitespace runs to single spaces"
# Context: runs of spaces inside a value become one space.
def test_internal_space_runs_collapse(run_xjq):
    result = run_xjq("//a/text()", stdin="<r><a>hello     world</a></r>")
    assert result.stdout == "hello world\n"


# Spec: "collapse internal whitespace runs to single spaces"
# Context: newlines and tabs count as whitespace and collapse too.
def test_newlines_and_tabs_collapse(run_xjq):
    doc = "<r><a>first\n\t  second\n\n third</a></r>"
    result = run_xjq("//a/text()", stdin=doc)
    assert result.stdout == "first second third\n"


# Spec: "collapse internal whitespace runs to single spaces"
# Context: collapsing also applies to attribute values.
def test_attribute_whitespace_collapses(run_xjq):
    result = run_xjq("//a/@v", stdin="<r><a v='x   \n  y'/></r>")
    assert result.stdout == "x y\n"


# Spec: "then join results with each on a newline"
# Context: several text matches are emitted one per line, in document order.
def test_multiple_text_results_one_per_line(run_xjq):
    doc = "<r><a>one</a><a>two</a><a>three</a></r>"
    result = run_xjq("//a/text()", stdin=doc)
    assert result.lines == ["one", "two", "three"]


# Spec: "then join results with each on a newline"
# Context: several attribute matches likewise land on separate lines.
def test_multiple_attribute_results_one_per_line(run_xjq):
    doc = "<r><a id='1'/><a id='2'/></r>"
    result = run_xjq("//a/@id", stdin=doc)
    assert result.lines == ["1", "2"]


# Spec: "then join results with each on a newline"
# Context: line-oriented output ends with a terminating newline.
# See AMBIGUITIES.md T4.
def test_output_ends_with_newline(run_xjq):
    result = run_xjq("//a/text()", stdin="<r><a>x</a><a>y</a></r>")
    assert result.stdout == "x\ny\n"


# Spec: "strip each result ... then join results with each on a newline"
# Context: a result that strips down to nothing keeps its position as a blank
# line rather than being dropped. See AMBIGUITIES.md T5.
def test_blank_results_are_kept(run_xjq):
    doc = "<r>  <a>x</a>  </r>"
    result = run_xjq("/r/text()", stdin=doc)
    assert result.returncode == 0
    assert result.lines == ["", ""]


# Spec: "XML node results: pretty-print serialized XML"
# Context: an element match is serialized as XML, not as its text.
def test_element_result_is_serialized(run_xjq):
    result = run_xjq("//a", stdin="<r><a v='1'>x</a></r>")
    assert result.returncode == 0
    assert result.stdout.strip() == '<a v="1">x</a>'


# Spec: "XML node results: pretty-print serialized XML"
# Context: nested children are indented onto their own lines.
# See AMBIGUITIES.md T7.
def test_element_result_is_indented(run_xjq):
    result = run_xjq("/r/a", stdin="<r><a><b>1</b><c>2</c></a></r>")
    expected = textwrap.dedent(
        """\
        <a>
          <b>1</b>
          <c>2</c>
        </a>"""
    )
    assert result.stdout.strip() == expected


# Spec: "XML node results: pretty-print serialized XML"
# Context: the serialization covers the whole subtree, including attributes on
# descendants.
def test_element_result_includes_subtree(run_xjq):
    doc = "<r><a><b id='9'>deep</b></a></r>"
    result = run_xjq("//a", stdin=doc)
    assert '<b id="9">deep</b>' in result.stdout


# Spec: "XML node results: pretty-print serialized XML"
# Context: trailing text following the selected element is not part of it.
def test_element_result_excludes_tail_text(run_xjq):
    result = run_xjq("//a", stdin="<r><a>x</a>tail</r>")
    assert "tail" not in result.stdout


# Spec: "XML node results: pretty-print serialized XML"
# Context: the document element itself can be selected.
def test_root_element_can_be_serialized(run_xjq):
    result = run_xjq("/r", stdin="<r><a>x</a></r>")
    assert result.returncode == 0
    assert result.stdout.strip().startswith("<r>")


# Spec: "when multiple XML nodes match, output only the first node"
# Context: three matching elements produce one serialization, the first in
# document order.
def test_only_first_of_multiple_nodes_is_output(run_xjq):
    doc = "<r><a>one</a><a>two</a><a>three</a></r>"
    result = run_xjq("//a", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.strip() == "<a>one</a>"


# Spec: "when multiple XML nodes match, output only the first node"
# Context: "first" follows document order across different element names.
def test_first_node_follows_document_order(run_xjq):
    doc = "<r><b>bee</b><a>ay</a></r>"
    result = run_xjq("//a|//b", stdin=doc)
    assert result.stdout.strip() == "<b>bee</b>"


# Spec: "No-match output: write nothing to stdout/stderr."
# Context: a valid query with an empty node set is silent on both streams.
def test_no_match_writes_nothing(run_xjq):
    result = run_xjq("//missing", stdin="<r><a>x</a></r>")
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "No-match output: write nothing to stdout/stderr."
# Context: an empty text/attribute node set is silent too — not a blank line.
def test_no_match_on_text_query_writes_nothing(run_xjq):
    result = run_xjq("//missing/@id", stdin="<r><a>x</a></r>")
    assert result.stdout == ""
    assert result.stderr == ""


# Spec: "No-match output: write nothing to stdout/stderr."
# Context: an empty string result from a string-valued function is not a match
# to print.
def test_empty_string_result_writes_nothing(run_xjq):
    result = run_xjq("string(//missing)", stdin="<r><a>x</a></r>")
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0
