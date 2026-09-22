"""Spec conformance tests for xjq.py.

The spec is split into minimal logical phrases; each test section quotes the
phrase (and the minimal context it needs) in a comment above the tests that
cover it. Interpretation choices are cross-referenced as Tn -> AMBIGUITIES.md.
"""

import textwrap

import pytest

from conftest import run

# ---------------------------------------------------------------------------
# Documents used across sections.
# ---------------------------------------------------------------------------

SIMPLE = "<root><item>a</item><item>b</item><item>c</item></root>"

ATTRS = (
    '<root><item id="one" cls="x">a</item>'
    '<item id="two" cls="y">b</item></root>'
)

NESTED = "<root><a><b>1</b><c>2</c></a><a><b>3</b></a></root>"

MIXED_CASE = "<Root><Item>upper</Item><item>lower</item></Root>"


# ===========================================================================
# Section 1
# Phrase: "Implement executable `xjq.py`"
# Context: CLI -- `python xjq.py [OPTIONS] QUERY [INFILE]`
# ===========================================================================


def test_script_file_exists():
    from conftest import XJQ

    assert XJQ.is_file(), "xjq.py must exist at the repository root"


def test_invocable_as_python_script():
    # `python xjq.py QUERY` runs and produces the query's result.
    r = run("//item/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a", "b", "c"]


# ===========================================================================
# Section 2
# Phrase: "`QUERY`: XPath expression."
# Context: CLI -- QUERY is the first positional argument.
# ===========================================================================


def test_query_is_first_positional_argument():
    r = run("//item[2]/text()", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "b"


def test_query_is_required():
    # Invoking with no QUERY at all is a usage error, not a success.
    from conftest import REPO_ROOT, XJQ
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(XJQ)],
        input=SIMPLE,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert proc.returncode != 0
    assert proc.stderr.strip() != ""


# ===========================================================================
# Section 3
# Phrase: "`INFILE`: accepted positional argument but not used."
# Context: CLI -- second, optional positional. (T9)
# SUPERSEDED by the file/first/compact spec: "`INFILE` takes precedence over
# stdin when both are present." The argument is now read; see
# tests/test_file_first_compact.py and the T9 update in AMBIGUITIES.md.
# ===========================================================================


def test_infile_positional_is_accepted(tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<other><item>from-file</item></other>")
    r = run("//item/text()", SIMPLE, str(infile))
    assert r.returncode == 0


def test_infile_now_wins_over_stdin(tmp_path):
    # Reversed by the later spec: the file exists and contains a *different*
    # document, and it is the one queried.
    infile = tmp_path / "doc.xml"
    infile.write_text("<other><item>from-file</item></other>")
    r = run("//item/text()", SIMPLE, str(infile))
    assert r.returncode == 0
    assert r.lines == ["from-file"]


def test_infile_must_now_exist(tmp_path):
    # Reversed by the later spec: "Missing/unreadable file: stderr message,
    # exit code `1`."
    r = run("//item/text()", SIMPLE, str(tmp_path / "nope.xml"))
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr != ""


# ===========================================================================
# Section 4
# Phrase: "Input source: stdin."
# Context: CLI.
# ===========================================================================


def test_document_is_read_from_stdin():
    r = run("//greeting/text()", "<greeting>hello</greeting>")
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"


def test_larger_stdin_document_is_read_fully():
    doc = "<root>" + "".join(f"<n>{i}</n>" for i in range(500)) + "</root>"
    r = run("//n/text()", doc)
    assert r.returncode == 0
    assert r.lines == [str(i) for i in range(500)]


# ===========================================================================
# Section 5
# Phrase: "Parse stdin as XML/HTML"
# Context: Behavior. (T1)
# ===========================================================================


def test_parses_plain_xml():
    r = run("//item/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a", "b", "c"]


def test_parses_xml_with_declaration():
    doc = '<?xml version="1.0" encoding="UTF-8"?>\n<root><item>a</item></root>'
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.stdout.strip() == "a"


def test_parses_html_shaped_document():
    doc = (
        "<html><head><title>T</title></head>"
        "<body><p class='x'>hello</p></body></html>"
    )
    r = run("//p/text()", doc)
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"


def test_parses_html_attributes_and_structure():
    doc = (
        "<html><body><ul>"
        '<li><a href="/one">One</a></li>'
        '<li><a href="/two">Two</a></li>'
        "</ul></body></html>"
    )
    r = run("//a/@href", doc)
    assert r.returncode == 0
    assert r.lines == ["/one", "/two"]


def test_parses_document_with_comments_and_cdata():
    doc = "<root><!-- note --><item><![CDATA[raw & text]]></item></root>"
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.stdout.strip() == "raw & text"


# ===========================================================================
# Section 6
# Phrase: "using case-sensitive element matching"
# Context: Behavior -- parsing stdin.
# ===========================================================================


def test_element_match_is_case_sensitive_exact_case_matches():
    r = run("//Item/text()", MIXED_CASE)
    assert r.returncode == 0
    assert r.lines == ["upper"]


def test_element_match_is_case_sensitive_other_case_does_not_match():
    r = run("//item/text()", MIXED_CASE)
    assert r.returncode == 0
    assert r.lines == ["lower"]


def test_element_case_is_preserved_in_serialized_output():
    r = run("//Root", "<Root><Item>x</Item></Root>")
    assert r.returncode == 0
    assert "<Root>" in r.stdout
    assert "<Item>" in r.stdout
    assert "<root>" not in r.stdout


def test_wrong_case_query_yields_no_match_not_an_error():
    r = run("//ROOT", MIXED_CASE)
    assert r.returncode == 0
    assert r.stdout == ""


def test_attribute_names_are_case_sensitive():
    doc = '<root><item ID="upper" id="lower"/></root>'
    r = run("//item/@ID", doc)
    assert r.returncode == 0
    assert r.stdout.strip() == "upper"


# ===========================================================================
# Section 7
# Phrase: "Evaluate `QUERY` with XPath 1.0."
# Context: Behavior.
# ===========================================================================


def test_absolute_path_expression():
    r = run("/root/item/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a", "b", "c"]


def test_descendant_axis_expression():
    r = run("//b/text()", NESTED)
    assert r.returncode == 0
    assert r.lines == ["1", "3"]


def test_positional_predicate():
    r = run("//item[1]/text()", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "a"


def test_attribute_predicate():
    r = run("//item[@id='two']/text()", ATTRS)
    assert r.returncode == 0
    assert r.stdout.strip() == "b"


def test_last_function():
    r = run("//item[last()]/text()", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "c"


def test_contains_function():
    doc = "<root><item>alpha</item><item>beta</item></root>"
    r = run("//item[contains(text(),'lph')]/text()", doc)
    assert r.returncode == 0
    assert r.stdout.strip() == "alpha"


def test_string_function_returns_text():
    r = run("string(//item[1])", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "a"


def test_union_expression():
    doc = "<root><a>1</a><b>2</b><c>3</c></root>"
    r = run("//a/text() | //c/text()", doc)
    assert r.returncode == 0
    assert r.lines == ["1", "3"]


def test_parent_axis():
    r = run("//b/parent::a/c/text()", NESTED)
    assert r.returncode == 0
    assert r.stdout.strip() == "2"


def test_xpath_2_syntax_is_rejected_as_xpath_1_0():
    # XPath 1.0 has no `for ... return`; an XPath 1.0 engine must reject it.
    r = run("for $x in //item return $x", SIMPLE)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


def test_count_function_numeric_result():
    # T4: integral numbers render without a trailing ".0".
    r = run("count(//item)", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "3"


def test_boolean_result():
    # T5: booleans render in XPath 1.0 lexical form.
    r = run("count(//item) > 2", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "true"


# ===========================================================================
# Section 8
# Phrase: "Exit code `0` on successful execution, including zero matches."
# Context: Behavior.
# ===========================================================================


def test_exit_zero_on_match():
    assert run("//item/text()", SIMPLE).returncode == 0


def test_exit_zero_on_zero_matches():
    assert run("//nonexistent", SIMPLE).returncode == 0


def test_exit_zero_on_zero_matches_for_attribute_query():
    assert run("//item/@missing", ATTRS).returncode == 0


def test_exit_zero_on_empty_string_result():
    assert run("string(//nope)", SIMPLE).returncode == 0


def test_exit_zero_on_false_boolean_result():
    assert run("count(//item) > 99", SIMPLE).returncode == 0


# ===========================================================================
# Section 9
# Phrase: "Text/attribute results: strip each result"
# Context: Output.
# ===========================================================================


def test_text_result_is_stripped():
    r = run("//item/text()", "<root><item>  padded  </item></root>")
    assert r.returncode == 0
    assert r.lines == ["padded"]


def test_text_result_newlines_are_stripped():
    r = run("//item/text()", "<root><item>\n   padded\n  </item></root>")
    assert r.returncode == 0
    assert r.lines == ["padded"]


def test_attribute_result_is_stripped():
    r = run("//item/@id", '<root><item id="  spaced  "/></root>')
    assert r.returncode == 0
    assert r.lines == ["spaced"]


def test_each_result_is_stripped_independently():
    doc = "<root><item> a </item><item>\tb\n</item></root>"
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.lines == ["a", "b"]


# ===========================================================================
# Section 10
# Phrase: "collapse internal whitespace runs to single spaces"
# Context: Output -- text/attribute results, after stripping.
# ===========================================================================


def test_internal_spaces_are_collapsed():
    r = run("//item/text()", "<root><item>hello     world</item></root>")
    assert r.returncode == 0
    assert r.lines == ["hello world"]


def test_internal_newlines_and_tabs_are_collapsed():
    doc = "<root><item>hello \n\t  big \n world</item></root>"
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.lines == ["hello big world"]


def test_strip_and_collapse_combined():
    doc = "<root><item>\n   hello   \t  world \n</item></root>"
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.lines == ["hello world"]


def test_attribute_whitespace_is_collapsed():
    r = run("//item/@cls", '<root><item cls="a   b\tc"/></root>')
    assert r.returncode == 0
    assert r.lines == ["a b c"]


def test_string_function_result_is_collapsed():
    doc = "<root><item>  a   b  </item></root>"
    r = run("string(//item)", doc)
    assert r.returncode == 0
    assert r.lines == ["a b"]


# ===========================================================================
# Section 11
# Phrase: "then join results with each on a newline"
# Context: Output -- text/attribute results.
# ===========================================================================


def test_multiple_text_results_one_per_line():
    r = run("//item/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a", "b", "c"]


def test_multiple_attribute_results_one_per_line():
    r = run("//item/@id", ATTRS)
    assert r.returncode == 0
    assert r.lines == ["one", "two"]


def test_single_result_is_one_line():
    r = run("//item[1]/text()", SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a"]


def test_results_keep_document_order():
    doc = "<root><item>z</item><item>y</item><item>x</item></root>"
    r = run("//item/text()", doc)
    assert r.lines == ["z", "y", "x"]


def test_multiline_text_result_becomes_a_single_line():
    # Collapsing happens before joining, so one match is always one line.
    doc = "<root><item>line one\nline two</item></root>"
    r = run("//item/text()", doc)
    assert r.returncode == 0
    assert r.lines == ["line one line two"]


# ===========================================================================
# Section 12
# Phrase: "XML node results: pretty-print serialized XML"
# Context: Output. (T2, T7)
# ===========================================================================


def _reparse(xml_text):
    from xml.etree import ElementTree as ET

    return ET.fromstring(xml_text)


def test_element_result_is_serialized_as_xml():
    r = run("//a[1]", NESTED)
    assert r.returncode == 0
    assert r.stdout.lstrip().startswith("<a>")
    node = _reparse(r.stdout.strip())
    assert node.tag == "a"
    assert [child.tag for child in node] == ["b", "c"]
    assert [child.text for child in node] == ["1", "2"]


def test_element_result_is_pretty_printed_over_multiple_lines():
    r = run("//a[1]", NESTED)
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.split("\n") if ln.strip()]
    assert len(lines) > 1, "nested element must be pretty-printed, not one line"


def test_pretty_print_indents_children_deeper_than_parent():
    r = run("/root", NESTED)
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.split("\n") if ln.strip()]
    parent_indent = len(lines[0]) - len(lines[0].lstrip())
    child_indent = len(lines[1]) - len(lines[1].lstrip())
    assert child_indent > parent_indent


def test_pretty_print_of_compact_input_adds_newlines():
    r = run("/root", "<root><a>1</a><b>2</b></root>")
    assert r.returncode == 0
    assert "\n" in r.stdout.strip()


def test_leaf_element_serializes_with_its_text():
    r = run("//b[1]", NESTED)
    assert r.returncode == 0
    assert r.stdout.strip() == "<b>1</b>"


def test_element_result_keeps_attributes():
    r = run("//item[1]", ATTRS)
    assert r.returncode == 0
    node = _reparse(r.stdout.strip())
    assert node.get("id") == "one"
    assert node.get("cls") == "x"
    assert node.text == "a"


def test_empty_element_result_serializes():
    r = run("//item", "<root><item/></root>")
    assert r.returncode == 0
    assert r.stdout.strip() in ("<item/>", "<item />", "<item></item>")


def test_root_element_result_serializes_whole_document():
    r = run("/root", SIMPLE)
    assert r.returncode == 0
    node = _reparse(r.stdout.strip())
    assert node.tag == "root"
    assert [c.text for c in node] == ["a", "b", "c"]


def test_element_result_does_not_include_sibling_tail_text():
    doc = "<root><a>1</a>TAIL<b>2</b></root>"
    r = run("//a", doc)
    assert r.returncode == 0
    assert "TAIL" not in r.stdout


def test_element_result_has_no_xml_declaration():
    r = run("/root", SIMPLE)
    assert r.returncode == 0
    assert "<?xml" not in r.stdout


def test_deeply_nested_element_pretty_print_is_reparseable():
    doc = "<r><l1><l2><l3>deep</l3></l2></l1></r>"
    r = run("/r", doc)
    assert r.returncode == 0
    node = _reparse(r.stdout.strip())
    assert node.find("l1/l2/l3").text == "deep"


# ===========================================================================
# Section 13
# Phrase: "when multiple XML nodes match, output only the first node"
# Context: Output -- XML node results.
# ===========================================================================


def test_only_first_of_multiple_element_matches_is_output():
    r = run("//item", SIMPLE)
    assert r.returncode == 0
    assert r.stdout.strip() == "<item>a</item>"
    assert "<item>b</item>" not in r.stdout
    assert "<item>c</item>" not in r.stdout


def test_first_node_is_first_in_document_order():
    r = run("//a", NESTED)
    assert r.returncode == 0
    node = _reparse(r.stdout.strip())
    assert [c.text for c in node] == ["1", "2"]


def test_single_element_match_is_output_unchanged_by_the_rule():
    r = run("//c", NESTED)
    assert r.returncode == 0
    assert r.stdout.strip() == "<c>2</c>"


def test_text_results_are_not_truncated_to_the_first():
    # The "first node only" rule is scoped to XML node results.
    r = run("//item/text()", SIMPLE)
    assert r.lines == ["a", "b", "c"]


# ===========================================================================
# Section 14
# Phrase: "No-match output: write nothing to stdout/stderr."
# Context: Output.
# ===========================================================================


def test_no_match_writes_nothing_to_stdout():
    r = run("//nonexistent", SIMPLE)
    assert r.stdout == ""


def test_no_match_writes_nothing_to_stderr():
    r = run("//nonexistent", SIMPLE)
    assert r.stderr == ""


def test_no_match_exits_zero():
    assert run("//nonexistent", SIMPLE).returncode == 0


def test_no_match_for_text_query_is_silent():
    r = run("//item/text()", "<root><item/></root>")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_no_match_for_attribute_query_is_silent():
    r = run("//item/@nope", ATTRS)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_no_match_for_predicate_query_is_silent():
    r = run("//item[@id='zzz']", ATTRS)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ===========================================================================
# Section 15
# Phrase: "Invalid XPath: stderr message, exit code `1`;
#          message should reference `xpath`."
# Context: Errors.
# ===========================================================================


@pytest.mark.parametrize(
    "bad_query",
    [
        "//[[",
        "//item[",
        "///",
        "//item[@id=",
        "not-a-function(",
        "//item/@",
        "*[",
    ],
)
def test_invalid_xpath_exits_one(bad_query):
    r = run(bad_query, SIMPLE)
    assert r.returncode == 1


@pytest.mark.parametrize("bad_query", ["//[[", "//item[", "//item[@id="])
def test_invalid_xpath_writes_message_to_stderr(bad_query):
    r = run(bad_query, SIMPLE)
    assert r.stderr.strip() != ""


@pytest.mark.parametrize("bad_query", ["//[[", "//item[", "//item[@id="])
def test_invalid_xpath_message_references_xpath(bad_query):
    r = run(bad_query, SIMPLE)
    assert "xpath" in r.stderr.lower()


def test_invalid_xpath_writes_nothing_to_stdout():
    r = run("//[[", SIMPLE)
    assert r.stdout == ""


def test_unknown_xpath_function_is_an_xpath_error():
    r = run("bogus(//item)", SIMPLE)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


def test_empty_query_string_is_an_xpath_error():
    r = run("", SIMPLE)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


# ===========================================================================
# Section 16
# Phrase: "Malformed/empty XML input: stderr message, exit code `1`;
#          message should reference `xml`/`parse`."
# Context: Errors.
# ===========================================================================

MALFORMED = [
    "<root><item>a</item>",          # unclosed root
    "<root><a></b></root>",          # mismatched tags
    "<root><item></root>",           # unclosed child
    "<root attr=unquoted/>",         # unquoted attribute value
    "<root>&badentity;</root>",      # undefined entity
    "<<>>",                          # garbage markup
]


@pytest.mark.parametrize("doc", MALFORMED)
def test_malformed_xml_exits_one(doc):
    r = run("//item", doc)
    assert r.returncode == 1


@pytest.mark.parametrize("doc", MALFORMED)
def test_malformed_xml_writes_message_to_stderr(doc):
    r = run("//item", doc)
    assert r.stderr.strip() != ""


@pytest.mark.parametrize("doc", MALFORMED)
def test_malformed_xml_message_references_xml_or_parse(doc):
    r = run("//item", doc)
    low = r.stderr.lower()
    assert "xml" in low or "parse" in low


@pytest.mark.parametrize("doc", MALFORMED)
def test_malformed_xml_writes_nothing_to_stdout(doc):
    assert run("//item", doc).stdout == ""


def test_empty_input_exits_one():
    r = run("//item", "")
    assert r.returncode == 1


def test_empty_input_message_references_xml_or_parse():
    r = run("//item", "")
    low = r.stderr.lower()
    assert r.stderr.strip() != ""
    assert "xml" in low or "parse" in low


def test_whitespace_only_input_exits_one():
    r = run("//item", "   \n\t  \n")
    assert r.returncode == 1
    low = r.stderr.lower()
    assert "xml" in low or "parse" in low


def test_non_markup_input_exits_one():
    r = run("//item", "this is not markup at all")
    assert r.returncode == 1
    low = r.stderr.lower()
    assert "xml" in low or "parse" in low


# ===========================================================================
# Section 17 -- interactions between phrases (integration)
# Context: whole-spec sanity checks over one realistic document.
# ===========================================================================

DOC = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <library name="City   Library">
      <book id="b1" lang="en">
        <title>  The   First  Book </title>
        <author>Ada</author>
      </book>
      <book id="b2" lang="fr">
        <title>Le Deuxieme</title>
        <author>Bo</author>
      </book>
    </library>
    """
)


def test_integration_titles_collapse_and_join():
    r = run("//title/text()", DOC)
    assert r.returncode == 0
    assert r.lines == ["The First Book", "Le Deuxieme"]


def test_integration_attribute_collapse():
    r = run("/library/@name", DOC)
    assert r.returncode == 0
    assert r.lines == ["City Library"]


def test_integration_ids_join():
    r = run("//book/@id", DOC)
    assert r.lines == ["b1", "b2"]


def test_integration_first_book_node_only():
    r = run("//book", DOC)
    assert r.returncode == 0
    node = _reparse(r.stdout.strip())
    assert node.get("id") == "b1"
    assert node.findtext("author") == "Ada"
    assert "Le Deuxieme" not in r.stdout
    assert 'id="b2"' not in r.stdout


def test_integration_predicate_then_text():
    r = run("//book[@lang='fr']/author/text()", DOC)
    assert r.returncode == 0
    assert r.lines == ["Bo"]


def test_integration_count():
    r = run("count(//book)", DOC)
    assert r.returncode == 0
    assert r.stdout.strip() == "2"


def test_integration_no_match_silent():
    r = run("//magazine", DOC)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
