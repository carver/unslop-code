"""`--first` and `--compact` output behavior.

Spec section: "## Output Rules"
"""

import textwrap

TEXT_DOC = "<r><a>one</a><a>two</a><a>three</a></r>"
NESTED_DOC = "<r><a><b>1</b><c>2</c></a><a><b>3</b></a></r>"


# Spec: "`--first` applies across text ... results"
# Context: three text matches become one line instead of three.
def test_first_keeps_one_text_result(run_xjq):
    result = run_xjq("--first", "//a/text()", stdin=TEXT_DOC)
    assert result.returncode == 0
    assert result.lines == ["one"]


# Spec: "`--first` applies across text ... results"
# Context: "first" is document order, not the order the union was written in.
def test_first_text_follows_document_order(run_xjq):
    result = run_xjq("--first", "//c/text()|//b/text()", stdin=NESTED_DOC)
    assert result.lines == ["1"]


# Spec: "`--first` applies across ... attribute ... results"
# Context: attribute matches are cut down the same way.
def test_first_keeps_one_attribute_result(run_xjq):
    doc = "<r><a id='1'/><a id='2'/><a id='3'/></r>"
    result = run_xjq("--first", "//a/@id", stdin=doc)
    assert result.lines == ["1"]


# Spec: "`--first` applies across ... XML-node results"
# Context: node output was already first-only, so the flag leaves it unchanged
# rather than widening or narrowing it. See AMBIGUITIES.md T30.
def test_first_matches_the_existing_node_behavior(run_xjq):
    with_flag = run_xjq("--first", "//a", stdin=TEXT_DOC)
    without_flag = run_xjq("//a", stdin=TEXT_DOC)
    assert with_flag.stdout == without_flag.stdout
    assert with_flag.stdout.strip() == "<a>one</a>"


# Spec: "`--first` applies across ... XML-node results"
# Context: the single node is still a full pretty-printed serialization.
def test_first_node_is_still_pretty_printed(run_xjq):
    result = run_xjq("--first", "//a", stdin=NESTED_DOC)
    expected = textwrap.dedent(
        """\
        <a>
          <b>1</b>
          <c>2</c>
        </a>"""
    )
    assert result.stdout.strip() == expected


# Spec: "`--first` with no matches remains silent (no output)."
# Context: an empty node set produces nothing on either stream, exit 0.
def test_first_with_no_matches_is_silent(run_xjq):
    result = run_xjq("--first", "//missing", stdin=TEXT_DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "`--first` with no matches remains silent (no output)."
# Context: an empty text/attribute node set is silent too — not a blank line.
def test_first_with_no_text_matches_is_silent(run_xjq):
    result = run_xjq("--first", "//missing/@id", stdin=TEXT_DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "`--first` applies across text ... results"
# Context: one match is unaffected by the flag.
def test_first_leaves_a_single_result_alone(run_xjq):
    result = run_xjq("--first", "//b/text()", stdin="<r><b>only</b></r>")
    assert result.stdout == "only\n"


# Spec: "return only first result" + base spec "strip each result, collapse
# internal whitespace runs"
# Context: the kept result is still normalised and still ends in a newline.
def test_first_result_is_still_normalised(run_xjq):
    doc = "<r><a>  spaced   out  </a><a>second</a></r>"
    result = run_xjq("--first", "//a/text()", stdin=doc)
    assert result.stdout == "spaced out\n"


# Spec: "return only first result" with `--text`
# Context: the cut happens on the printed results, after the text flag expands
# each element, so the output is a single line. See AMBIGUITIES.md T28.
def test_first_cuts_after_text_extraction(run_xjq):
    doc = "<r><a>x<i/>y</a><a>z</a></r>"
    result = run_xjq("--first", "--text", "//a", stdin=doc)
    assert result.lines == ["x"]


# Spec: "return only first result" with `--text-all`
# Context: descendant extraction is cut the same way.
def test_first_cuts_after_descendant_extraction(run_xjq):
    doc = "<r><a>x<i>deep</i></a><a>z</a></r>"
    result = run_xjq("--first", "--text-all", "//a", stdin=doc)
    assert result.lines == ["x"]


# Spec: "`--first` applies across text ... results"
# Context: CSS `::text` queries return text results and are cut like any
# other.
def test_first_applies_to_css_text_queries(run_xjq):
    result = run_xjq("--first", "--css", "a::text", stdin=TEXT_DOC)
    assert result.lines == ["one"]


# Spec: "`--compact` affects XML serialization only: compact XML output has no
# added pretty-print formatting."
# Context: a nested element that pretty-printing would indent stays on one
# line.
def test_compact_removes_added_indentation(run_xjq):
    result = run_xjq("--compact", "//a", stdin=NESTED_DOC)
    assert result.stdout == "<a><b>1</b><c>2</c></a>\n"


# Spec: "compact XML output has no added pretty-print formatting"
# Context: the difference is visible against the default rendering.
def test_compact_differs_from_pretty_output(run_xjq):
    compact = run_xjq("--compact", "//a", stdin=NESTED_DOC).stdout
    pretty = run_xjq("//a", stdin=NESTED_DOC).stdout
    assert "\n" in pretty.strip()
    assert "\n" not in compact.strip()


# Spec: "compact XML output has no added pretty-print formatting"
# Context: attributes and text content are untouched by compaction.
def test_compact_keeps_attributes_and_text(run_xjq):
    result = run_xjq("--compact", "//a", stdin="<r><a v='1'>x</a></r>")
    assert result.stdout == '<a v="1">x</a>\n'


# Spec: "no *added* pretty-print formatting"
# Context: whitespace the source document really contains is content, not
# added formatting, so it survives. See AMBIGUITIES.md T31.
def test_compact_keeps_source_whitespace(run_xjq):
    doc = "<r><a>\n  <b>1</b>\n</a></r>"
    result = run_xjq("--compact", "//a", stdin=doc)
    assert result.stdout == "<a>\n  <b>1</b>\n</a>\n"


# Spec: "`--compact` affects XML serialization only"
# Context: text results are unchanged by the flag.
def test_compact_leaves_text_results_alone(run_xjq):
    with_flag = run_xjq("--compact", "//a/text()", stdin=TEXT_DOC)
    without_flag = run_xjq("//a/text()", stdin=TEXT_DOC)
    assert with_flag.stdout == without_flag.stdout == "one\ntwo\nthree\n"


# Spec: "`--compact` affects XML serialization only"
# Context: attribute results are unchanged by the flag.
def test_compact_leaves_attribute_results_alone(run_xjq):
    doc = "<r><a v='  x   y  '/></r>"
    result = run_xjq("--compact", "//a/@v", stdin=doc)
    assert result.stdout == "x y\n"


# Spec: "`--compact` affects XML serialization only"
# Context: no matches is still silence, not an empty serialization.
def test_compact_with_no_matches_is_silent(run_xjq):
    result = run_xjq("--compact", "//missing", stdin=TEXT_DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "For JSON-derived input, `--compact` still applies to resulting XML
# output."
# Context: the tree built from JSON serializes without indentation.
def test_compact_applies_to_json_derived_xml(run_xjq):
    result = run_xjq("--compact", "//user", stdin='{"user": {"name": "ada"}}')
    assert result.stdout == '<user type="dict"><name type="str">ada</name></user>\n'


# Spec: "For JSON-derived input, `--compact` still applies"
# Context: without the flag the same JSON input is pretty-printed, so the flag
# is what made the difference.
def test_json_derived_xml_is_pretty_by_default(run_xjq):
    result = run_xjq("//user", stdin='{"user": {"name": "ada"}}')
    expected = textwrap.dedent(
        """\
        <user type="dict">
          <name type="str">ada</name>
        </user>"""
    )
    assert result.stdout.strip() == expected


# Spec: "For JSON-derived input, `--compact` still applies"
# Context: JSON arrays compact too, `<item>` children and all.
def test_compact_applies_to_json_arrays(run_xjq):
    result = run_xjq("--compact", "/root", stdin='[1, 2]')
    assert result.stdout == (
        '<root><item type="int">1</item><item type="int">2</item></root>\n'
    )


# Spec: "`--first` ... `--compact`"
# Context: the two flags compose — the first node, serialized compactly.
def test_first_and_compact_together(run_xjq):
    result = run_xjq("--first", "--compact", "//a", stdin=NESTED_DOC)
    assert result.stdout == "<a><b>1</b><c>2</c></a>\n"


# Spec: "`--compact` affects XML serialization only"
# Context: file input reaches the same serializer as stdin input.
def test_compact_applies_to_file_input(run_xjq, tmp_path):
    source = tmp_path / "doc.json"
    source.write_text('{"user": {"name": "ada"}}')
    result = run_xjq("--compact", "//name", str(source))
    assert result.stdout == '<name type="str">ada</name>\n'
