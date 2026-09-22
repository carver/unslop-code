"""The `--first` and `--compact` output flags."""

from conftest import BOOKS, PAGE

SPACED = '<r><t id="  a  b  ">  one  </t><t>two</t><t>three</t></r>'


# Spec: "`-f`, `--first`: return only first result." -- the long form.
def test_first_long_form(run_xjq):
    assert run_xjq("--first", "//title/text()", stdin=BOOKS).stdout == "Dune"


# Spec: "`-f`, `--first`: return only first result." -- the short form.
def test_first_short_form(run_xjq):
    assert run_xjq("-f", "//title/text()", stdin=BOOKS).stdout == "Dune"


# Spec: "`-c`, `--compact`: compact output mode." -- both spellings are accepted.
def test_compact_flag_spellings(run_xjq):
    expected = "<a><b>x</b></a>"
    doc = "<a>\n  <b>x</b>\n</a>"
    assert run_xjq("--compact", "/a", stdin=doc).stdout.rstrip("\n") == expected
    assert run_xjq("-c", "/a", stdin=doc).stdout.rstrip("\n") == expected


# Spec: "`--first` applies across text ... results."
def test_first_applies_to_text_results(run_xjq):
    result = run_xjq("-f", "//t/text()", stdin=SPACED)
    assert result.returncode == 0
    assert result.stdout == "one"


# Spec: "`--first` applies across ... attribute ... results."
def test_first_applies_to_attribute_results(run_xjq):
    assert run_xjq("-f", "//book/@id", stdin=BOOKS).stdout == "b1"


# Spec: "`--first` applies across ... attribute ... results." -- the one result
# kept is still stripped and whitespace-collapsed.
def test_first_attribute_result_is_still_normalized(run_xjq):
    assert run_xjq("-f", "//t/@id", stdin=SPACED).stdout == "a b"


# Spec: "`--first` applies across ... XML-node results."
def test_first_applies_to_xml_node_results(run_xjq):
    result = run_xjq("-f", "//book", stdin=BOOKS)
    assert result.stdout.count("<book") == 1
    assert "Dune" in result.stdout
    assert "Les Miserables" not in result.stdout


# Spec: "`--first` applies across ... XML-node results." -- node output already
# stops at the first node, so the flag leaves it unchanged (AMBIGUITIES T27).
def test_first_matches_the_default_node_output(run_xjq):
    assert run_xjq("-f", "//title", stdin=BOOKS).stdout == run_xjq(
        "//title", stdin=BOOKS
    ).stdout


# Spec: "`--first` applies across text ... results." -- it composes with the
# text-extraction flags, keeping the first matched element's text.
def test_first_with_text_extraction(run_xjq):
    assert run_xjq("-f", "--text-all", "//div", stdin=PAGE).stdout.startswith("First")
    assert run_xjq("-f", "-t", "//h1", stdin=PAGE).stdout == "First"


# Spec: "`--first` applies across text ... results." -- and with CSS mode.
def test_first_with_css_selectors(run_xjq):
    assert run_xjq("-f", "--css", "h1::text", stdin=PAGE).stdout == "First"


# Spec: "`--first` with no matches remains silent (no output)."
def test_first_with_no_matches_is_silent(run_xjq):
    result = run_xjq("-f", "//missing/text()", stdin=BOOKS)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Spec: "`--first` with no matches remains silent (no output)." -- for node and
# attribute queries too.
def test_first_with_no_node_or_attribute_matches(run_xjq):
    assert run_xjq("-f", "//missing", stdin=BOOKS).stdout == ""
    assert run_xjq("-f", "//book/@missing", stdin=BOOKS).stdout == ""


# Spec: "`--first` ... return only first result." -- one result stays one result,
# with no trailing newline added.
def test_first_leaves_a_single_result_alone(run_xjq):
    result = run_xjq("-f", "//book[2]/title/text()", stdin=BOOKS)
    assert result.stdout == "Les Miserables"


# Spec: "`--compact` affects XML serialization only" -- text output is untouched.
def test_compact_does_not_change_text_output(run_xjq):
    assert run_xjq("-c", "//title/text()", stdin=BOOKS).stdout == "Dune\nLes Miserables"
    assert run_xjq("-c", "//book/@id", stdin=BOOKS).stdout == "b1\nb2"


# Spec: "`--compact` affects XML serialization only" -- nor extracted text.
def test_compact_does_not_change_extracted_text(run_xjq):
    plain = run_xjq("--text-all", "//div", stdin=PAGE).stdout
    assert run_xjq("-c", "--text-all", "//div", stdin=PAGE).stdout == plain


# Spec: "compact XML output has no added pretty-print formatting."
def test_compact_xml_is_a_single_line(run_xjq):
    result = run_xjq("-c", "//book[1]", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == (
        '<book id="b1" lang="en"><title>Dune</title>'
        "<author>Frank Herbert</author></book>"
    )


# Spec: "compact XML output has no added pretty-print formatting." -- the
# indentation the source carried is layout, not content, and goes too
# (AMBIGUITIES T28).
def test_compact_drops_source_layout_whitespace(run_xjq):
    doc = "<a>\n\t<b>\n\t\t<c>x</c>\n\t</b>\n</a>"
    assert run_xjq("-c", "/a", stdin=doc).stdout.rstrip("\n") == "<a><b><c>x</c></b></a>"


# Spec: "compact XML output has no added pretty-print formatting." -- text that
# carries content is mixed content and survives verbatim.
def test_compact_keeps_mixed_content_text(run_xjq):
    doc = "<p>Hello <b>World</b>!</p>"
    assert run_xjq("-c", "/p", stdin=doc).stdout.rstrip("\n") == doc


# Spec: "compact XML output has no added pretty-print formatting." -- without the
# flag the same document is still pretty-printed.
def test_without_compact_output_is_pretty_printed(run_xjq):
    assert run_xjq("/a", stdin="<a><b>x</b></a>").stdout.rstrip("\n") == (
        "<a>\n  <b>x</b>\n</a>"
    )


# Spec: "For JSON-derived input, `--compact` still applies to resulting XML
# output."
def test_compact_applies_to_json_derived_xml(run_xjq):
    result = run_xjq("-c", "/root", stdin='{"a": "x", "b": [1]}')
    assert result.stdout.rstrip("\n") == (
        '<root><a type="str">x</a><b type="list"><item type="int">1</item></b></root>'
    )


# Spec: "For JSON-derived input, `--compact` still applies to resulting XML
# output." -- the pretty-printed form is what the flag replaces.
def test_json_derived_xml_is_pretty_printed_without_compact(run_xjq):
    result = run_xjq("/root", stdin='{"a": "x"}')
    assert result.stdout.rstrip("\n") == '<root>\n  <a type="str">x</a>\n</root>'


# Spec: "For JSON-derived input, `--compact` still applies" -- including when the
# file is the input source.
def test_compact_json_from_a_file(run_xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_text('{"a": "x"}')
    result = run_xjq("-c", "/root", str(infile))
    assert result.stdout.rstrip("\n") == '<root><a type="str">x</a></root>'


# Spec: "`-f`, `--first`" and "`-c`, `--compact`" -- the two flags combine.
def test_first_and_compact_together(run_xjq):
    result = run_xjq("-f", "-c", "//book", stdin=BOOKS)
    assert result.stdout.rstrip("\n").startswith('<book id="b1" lang="en"><title>')
    assert "Les Miserables" not in result.stdout


# Spec: "`-f`, `--first`" and "`-c`, `--compact`" -- and they work on file input.
def test_flags_apply_to_file_input(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(BOOKS)
    assert run_xjq("-f", "//title/text()", str(infile)).stdout == "Dune"
    assert run_xjq("-c", "//title", str(infile)).stdout.rstrip("\n") == (
        "<title>Dune</title>"
    )
