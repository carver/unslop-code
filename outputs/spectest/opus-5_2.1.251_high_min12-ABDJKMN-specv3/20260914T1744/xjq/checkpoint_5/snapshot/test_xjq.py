"""Test suite for xjq.py, derived phrase-by-phrase from the spec.

Each section carries a comment quoting the spec phrase it covers, plus the
context needed to read it. Interpretation choices are cross-referenced to
AMBIGUITIES.md entries (T1..T7).
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
XJQ = os.path.join(HERE, "xjq.py")


def run(*args, stdin=""):
    """Invoke `python xjq.py <args>` feeding `stdin`; return CompletedProcess (bytes)."""
    if isinstance(stdin, str):
        stdin = stdin.encode("utf-8")
    return subprocess.run(
        [sys.executable, XJQ, *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def out(proc):
    return proc.stdout.decode("utf-8")


def err(proc):
    return proc.stderr.decode("utf-8")


# Shared fixtures -----------------------------------------------------------

CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<catalog count="2">
  <book id="b1" lang="en">
    <title>XPath Basics</title>
    <author>Ada</author>
    <price currency="USD">29.99</price>
  </book>
  <book id="b2" lang="fr">
    <title>XPath Avance</title>
    <author>Remy</author>
    <price currency="EUR">31.50</price>
  </book>
</catalog>
"""

FLAT = "<root><a>one</a><a>two</a><b>three</b></root>"


# ===========================================================================
# CLI
# ===========================================================================

# Spec: "Implement executable `xjq.py`"
# Context: the deliverable is a script at xjq.py, runnable by the Python
# interpreter. Executable also implies a shebang and the executable bit.


class TestExecutableScript:
    def test_xjq_py_exists(self):
        assert os.path.isfile(XJQ)

    def test_has_shebang(self):
        with open(XJQ, "rb") as fh:
            assert fh.readline().startswith(b"#!")

    def test_executable_bit_set(self):
        assert os.access(XJQ, os.X_OK)

    def test_runs_directly_as_a_program(self):
        # Executed via its own shebang rather than `python xjq.py`.
        proc = subprocess.run(
            [XJQ, "//a/text()"],
            input=FLAT.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        assert proc.stdout.decode() == "one\ntwo"


# Spec: "`python xjq.py [OPTIONS] QUERY [INFILE]`"
# Context: the command line shape. QUERY is required and positional; INFILE is
# an optional trailing positional; OPTIONS is a (here empty) flag slot. See T6.


class TestCommandLineShape:
    def test_query_is_required(self):
        proc = run(stdin=FLAT)
        assert proc.returncode != 0

    def test_query_only_is_accepted(self):
        proc = run("//a/text()", stdin=FLAT)
        assert proc.returncode == 0

    def test_query_plus_infile_is_accepted(self, tmp_path):
        # The file-input spec makes INFILE a real, opened path.
        doc = tmp_path / "in.xml"
        doc.write_text(FLAT, encoding="utf-8")
        proc = run("//a/text()", str(doc))
        assert proc.returncode == 0

    def test_third_positional_is_ignored(self, tmp_path):
        # Retired and reversed by the file-input spec (this used to assert
        # rejection). Extra positionals are now ignored. See T33.
        doc = tmp_path / "in.xml"
        doc.write_text(FLAT, encoding="utf-8")
        proc = run("//a/text()", str(doc), "f2.xml")
        assert proc.returncode == 0

    def test_help_flag_is_available_and_succeeds(self):
        # T6: the only option a spec-with-no-options can offer.
        proc = run("--help", stdin=FLAT)
        assert proc.returncode == 0
        assert "usage" in out(proc).lower()

    def test_unknown_option_is_rejected(self):
        # T6 choice: argparse default, unknown flags are an error.
        proc = run("--definitely-not-an-option", "//a", stdin=FLAT)
        assert proc.returncode != 0

    def test_query_starting_with_dash_after_double_dash(self):
        # A query may legitimately need to survive option parsing.
        proc = run("--", "//a/text()", stdin=FLAT)
        assert proc.returncode == 0
        assert out(proc) == "one\ntwo"


# Spec: "`QUERY`: XPath expression."
# Context: the first positional is the expression to evaluate, not a file.


class TestQueryArgument:
    def test_query_is_evaluated_as_xpath_not_treated_as_literal(self):
        proc = run("//b/text()", stdin=FLAT)
        assert out(proc) == "three"

    def test_absolute_path_query(self):
        proc = run("/root/a/text()", stdin=FLAT)
        assert out(proc) == "one\ntwo"

    def test_predicate_query(self):
        proc = run("//a[2]/text()", stdin=FLAT)
        assert out(proc) == "two"

    def test_attribute_predicate_query(self):
        proc = run("//book[@id='b2']/title/text()", stdin=CATALOG)
        assert out(proc) == "XPath Avance"


# Spec: "`INFILE`: accepted positional argument but not used."
# Context: RETIRED by the file-input spec, which opens INFILE and gives it
# precedence over stdin. See T7 (annotation) and the "Input Source" section of
# the file-input tests below, which replaces every fixture that lived here.


# Spec: "Input source: stdin."
# Context: the document always comes from standard input.


class TestStdinIsTheInputSource:
    def test_document_comes_from_stdin(self):
        proc = run("//a/text()", stdin="<root><a>from-stdin</a></root>")
        assert out(proc) == "from-stdin"

    def test_stdin_read_as_bytes_honours_encoding_declaration(self):
        doc = '<?xml version="1.0" encoding="UTF-8"?><root><a>café</a></root>'
        proc = run("//a/text()", stdin=doc)
        assert proc.returncode == 0
        assert out(proc) == "café"

    def test_latin1_declared_encoding(self):
        doc = '<?xml version="1.0" encoding="ISO-8859-1"?><root><a>café</a></root>'
        proc = subprocess.run(
            [sys.executable, XJQ, "//a/text()"],
            input=doc.encode("iso-8859-1"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        assert proc.stdout.decode("utf-8") == "café"

    def test_large_stdin_is_consumed_fully(self):
        body = "".join(f"<a>{i}</a>" for i in range(5000))
        proc = run("count(//a)", stdin=f"<root>{body}</root>")
        assert proc.returncode == 0
        assert out(proc) == "5000"


# ===========================================================================
# Behavior
# ===========================================================================

# Spec: "Parse stdin as XML/HTML using case-sensitive element matching."
# Context: element (and attribute) names keep their source case, so queries
# match case-sensitively; the HTML parser's lower-casing must not apply. See T1.


class TestCaseSensitiveMatching:
    DOC = "<Root><Book><Title>Cased</Title></Book><book><title>lower</title></book></Root>"

    def test_exact_case_matches(self):
        proc = run("//Title/text()", stdin=self.DOC)
        assert proc.returncode == 0
        assert out(proc) == "Cased"

    def test_lowercase_query_matches_only_lowercase_element(self):
        proc = run("//title/text()", stdin=self.DOC)
        assert out(proc) == "lower"

    def test_wrong_case_does_not_match(self):
        proc = run("//TITLE/text()", stdin=self.DOC)
        assert proc.returncode == 0
        assert out(proc) == ""

    def test_root_element_is_case_sensitive(self):
        assert out(run("/Root/Book/Title/text()", stdin=self.DOC)) == "Cased"
        assert out(run("/root/book/title/text()", stdin=self.DOC)) == ""

    def test_attribute_names_are_case_sensitive(self):
        doc = '<r><x ID="upper" id="lower"/></r>'
        assert out(run("//x/@ID", stdin=doc)) == "upper"
        assert out(run("//x/@id", stdin=doc)) == "lower"

    def test_html_like_document_parses_when_well_formed(self):
        # The "HTML" half of the phrase: XHTML-shaped input still works.
        doc = "<html><body><p>hello</p><br/></body></html>"
        proc = run("//p/text()", stdin=doc)
        assert proc.returncode == 0
        assert out(proc) == "hello"

    def test_camelcase_html_tag_is_not_folded(self):
        doc = "<html><body><myWidget>kept</myWidget></body></html>"
        assert out(run("//myWidget/text()", stdin=doc)) == "kept"
        assert out(run("//mywidget/text()", stdin=doc)) == ""


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: the query language is XPath 1.0 - its axes, node tests, operators
# and its core function library.


class TestXPath10Evaluation:
    def test_descendant_axis(self):
        assert out(run("//title/text()", stdin=CATALOG)) == "XPath Basics\nXPath Avance"

    def test_child_axis_named(self):
        assert out(run("/catalog/book/author/text()", stdin=CATALOG)) == "Ada\nRemy"

    def test_parent_axis(self):
        assert out(run("//title[text()='XPath Basics']/../@id", stdin=CATALOG)) == "b1"

    def test_following_sibling_axis(self):
        doc = "<r><a>1</a><b>2</b><c>3</c></r>"
        assert out(run("//a/following-sibling::*/text()", stdin=doc)) == "2\n3"

    def test_ancestor_axis(self):
        assert out(run("//author/ancestor::catalog/@count", stdin=CATALOG)) == "2"

    def test_attribute_axis_wildcard(self):
        assert out(run("//book[1]/@*", stdin=CATALOG)) == "b1\nen"

    def test_union_operator(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("//a/text() | //b/text()", stdin=doc)) == "1\n2"

    def test_position_and_last_functions(self):
        assert out(run("//book[last()]/@id", stdin=CATALOG)) == "b2"

    def test_contains_function(self):
        assert out(run("//title[contains(., 'Avance')]/text()", stdin=CATALOG)) == "XPath Avance"

    def test_starts_with_function(self):
        assert out(run("//title[starts-with(., 'XPath')]/text()", stdin=CATALOG)) == (
            "XPath Basics\nXPath Avance"
        )

    def test_string_function_returns_a_string_result(self):
        assert out(run("string(//title)", stdin=CATALOG)) == "XPath Basics"

    def test_concat_function(self):
        assert out(run("concat(//book[1]/@id, '-', //book[2]/@id)", stdin=CATALOG)) == "b1-b2"

    def test_name_and_local_name_functions(self):
        assert out(run("name(/*)", stdin=CATALOG)) == "catalog"
        assert out(run("local-name(/*)", stdin=CATALOG)) == "catalog"

    def test_normalize_space_function(self):
        assert out(run("normalize-space(//book[1]/title)", stdin=CATALOG)) == "XPath Basics"

    def test_numeric_predicate_with_comparison(self):
        assert out(run("//price[. > 30]/@currency", stdin=CATALOG)) == "EUR"

    def test_and_or_in_predicate(self):
        q = "//book[@lang='en' or @lang='de']/@id"
        assert out(run(q, stdin=CATALOG)) == "b1"

    def test_not_function(self):
        assert out(run("//book[not(@lang='en')]/@id", stdin=CATALOG)) == "b2"

    def test_xpath_20_only_construct_is_not_available(self):
        # XPath 1.0 has no `matches()`; requesting it is an invalid expression.
        proc = run("//a[matches(., 'x')]", stdin=FLAT)
        assert proc.returncode == 1

    def test_comment_node_test(self):
        doc = "<r><!-- note --><a>x</a></r>"
        proc = run("//comment()", stdin=doc)
        assert proc.returncode == 0

    def test_namespaced_document_local_name_query(self):
        doc = '<r xmlns:n="http://example.com/n"><n:item>ns-text</n:item></r>'
        assert out(run("//*[local-name()='item']/text()", stdin=doc)) == "ns-text"

    def test_undeclared_prefix_in_query_is_an_error(self):
        doc = '<r xmlns:n="http://example.com/n"><n:item>x</n:item></r>'
        proc = run("//n:item", stdin=doc)
        assert proc.returncode == 1


# Spec: "Exit code `0` on successful execution, including zero matches."
# Context: an empty result set is success, not failure.


class TestExitCodeZero:
    def test_match_exits_zero(self):
        assert run("//a/text()", stdin=FLAT).returncode == 0

    def test_zero_matches_exits_zero(self):
        assert run("//nope", stdin=FLAT).returncode == 0

    def test_zero_matches_on_text_query_exits_zero(self):
        assert run("//nope/text()", stdin=FLAT).returncode == 0

    def test_zero_matches_on_attribute_query_exits_zero(self):
        assert run("//a/@missing", stdin=FLAT).returncode == 0

    def test_false_boolean_result_exits_zero(self):
        assert run("//a and false()", stdin=FLAT).returncode == 0

    def test_zero_count_exits_zero(self):
        assert run("count(//nope)", stdin=FLAT).returncode == 0

    def test_xml_node_result_exits_zero(self):
        assert run("//a", stdin=FLAT).returncode == 0


# ===========================================================================
# Output
# ===========================================================================

# Spec: "Text/attribute results: strip each result, collapse internal
# whitespace runs to single spaces, then join results with each on a newline.
# No trailing newline."
# Context: normalization applies per result, before joining.


class TestTextAndAttributeOutput:
    def test_single_text_result(self):
        assert out(run("//b/text()", stdin=FLAT)) == "three"

    def test_single_attribute_result(self):
        assert out(run("//book[1]/@id", stdin=CATALOG)) == "b1"

    def test_multiple_results_joined_by_newline(self):
        assert out(run("//a/text()", stdin=FLAT)) == "one\ntwo"

    def test_multiple_attribute_results_joined_by_newline(self):
        assert out(run("//book/@id", stdin=CATALOG)) == "b1\nb2"

    def test_leading_and_trailing_whitespace_is_stripped(self):
        doc = "<r><a>   padded   </a></r>"
        assert out(run("//a/text()", stdin=doc)) == "padded"

    def test_internal_whitespace_runs_collapse_to_one_space(self):
        doc = "<r><a>many     spaces      here</a></r>"
        assert out(run("//a/text()", stdin=doc)) == "many spaces here"

    def test_internal_newlines_and_tabs_collapse_to_one_space(self):
        doc = "<r><a>line one\n\n\tline two\r\n  line three</a></r>"
        assert out(run("//a/text()", stdin=doc)) == "line one line two line three"

    def test_strip_and_collapse_combined(self):
        doc = "<r><a>\n\t  alpha \t beta  \n </a></r>"
        assert out(run("//a/text()", stdin=doc)) == "alpha beta"

    def test_attribute_values_are_normalized_too(self):
        doc = '<r><a t="  spaced    out  "/></r>'
        assert out(run("//a/@t", stdin=doc)) == "spaced out"

    def test_normalization_is_per_result_then_joined(self):
        doc = "<r><a>  x   y  </a><a> z \n w </a></r>"
        assert out(run("//a/text()", stdin=doc)) == "x y\nz w"

    def test_no_trailing_newline_single_result(self):
        assert not out(run("//b/text()", stdin=FLAT)).endswith("\n")

    def test_no_trailing_newline_multiple_results(self):
        o = out(run("//a/text()", stdin=FLAT))
        assert not o.endswith("\n")
        assert o.count("\n") == 1

    def test_element_string_value_via_string_function_is_text_output(self):
        assert out(run("string(//book[1]/author)", stdin=CATALOG)) == "Ada"

    def test_nbsp_and_unicode_text_preserved(self):
        doc = "<r><a>café à la carte</a></r>"
        assert out(run("//a/text()", stdin=doc)) == "café à la carte"

    def test_entity_references_are_resolved_before_output(self):
        doc = "<r><a>a &amp; b &lt;c&gt;</a></r>"
        assert out(run("//a/text()", stdin=doc)) == "a & b <c>"

    def test_cdata_text_is_returned_as_text(self):
        doc = "<r><a><![CDATA[raw   <text>]]></a></r>"
        assert out(run("//a/text()", stdin=doc)) == "raw <text>"

    def test_mixed_content_yields_separate_text_nodes(self):
        doc = "<p>Hello <b>bold</b> world</p>"
        assert out(run("//p/text()", stdin=doc)) == "Hello\nworld"

    # T3: XPath 1.0 string semantics for non-node-set results.
    def test_count_renders_as_integer(self):
        assert out(run("count(//a)", stdin=FLAT)) == "2"

    def test_zero_count_renders_as_zero(self):
        assert out(run("count(//nope)", stdin=FLAT)) == "0"

    def test_non_integral_number_keeps_fraction(self):
        assert out(run("number(//price[1])", stdin=CATALOG)) == "29.99"

    def test_arithmetic_result(self):
        assert out(run("1 + 2", stdin=FLAT)) == "3"

    def test_true_boolean_renders_lowercase(self):
        assert out(run("count(//a) = 2", stdin=FLAT)) == "true"

    def test_false_boolean_renders_lowercase(self):
        assert out(run("count(//a) = 99", stdin=FLAT)) == "false"

    # T2: results that normalize to empty are kept, not filtered.
    def test_whitespace_only_text_node_keeps_its_slot(self):
        doc = "<r><a>x</a><a>   </a><a>y</a></r>"
        assert out(run("//a/text()", stdin=doc)) == "x\n\ny"

    def test_empty_attribute_value_keeps_its_slot(self):
        doc = '<r><a t="x"/><a t=""/></r>'
        assert out(run("//a/@t", stdin=doc)) == "x\n"


# Spec: "XML node results: pretty-print serialized XML; when multiple XML nodes
# match, output only the first node."
# Context: element results are serialized, not string-valued. See T4, T5.


class TestXmlNodeOutput:
    def test_element_result_is_serialized_as_xml(self):
        o = out(run("//b", stdin=FLAT))
        assert "<b>" in o and "three" in o and "</b>" in o

    def test_element_result_is_not_string_valued(self):
        o = out(run("//b", stdin=FLAT))
        assert o.strip() != "three"

    def test_only_the_first_of_multiple_nodes_is_output(self):
        o = out(run("//a", stdin=FLAT))
        assert "one" in o
        assert "two" not in o

    def test_first_node_is_document_order_first(self):
        o = out(run("//book", stdin=CATALOG))
        assert "XPath Basics" in o
        assert "XPath Avance" not in o

    def test_attributes_are_included_in_serialization(self):
        o = out(run("//book[2]", stdin=CATALOG))
        assert 'id="b2"' in o
        assert 'lang="fr"' in o

    def test_descendants_are_included(self):
        o = out(run("//book[1]", stdin=CATALOG))
        assert "<title>" in o
        assert "<author>" in o
        assert "<price" in o

    def test_root_element_query_serializes_whole_document(self):
        o = out(run("/catalog", stdin=CATALOG))
        assert "<catalog" in o
        assert "XPath Basics" in o
        assert "XPath Avance" in o

    def test_pretty_print_indents_nested_children(self):
        # T5: children appear on their own lines, indented relative to parent.
        o = out(run("//book[1]", stdin=CATALOG))
        lines = o.split("\n")
        assert lines[0].startswith("<book")
        title_line = next(ln for ln in lines if "<title>" in ln)
        assert title_line.startswith(" ")

    def test_pretty_print_reindents_from_column_zero(self):
        # T5 choice: the selected node's own closing tag is not left carrying
        # the source document's indentation.
        o = out(run("//book[1]", stdin=CATALOG)).rstrip("\n")
        assert o.split("\n")[-1] == "</book>"

    def test_pretty_print_of_single_line_source(self):
        doc = "<r><outer><inner>v</inner></outer></r>"
        o = out(run("//outer", stdin=doc))
        assert o.count("\n") >= 1
        assert "<inner>v</inner>" in o

    def test_empty_element_serializes(self):
        doc = "<r><e/></r>"
        o = out(run("//e", stdin=doc))
        assert "<e/>" in o or "<e></e>" in o

    def test_element_with_only_text_stays_on_one_line(self):
        doc = "<r><a>one</a></r>"
        assert out(run("//a", stdin=doc)).rstrip("\n") == "<a>one</a>"

    def test_text_content_whitespace_is_not_collapsed_in_xml_mode(self):
        doc = "<r><a>keep    me</a></r>"
        assert "keep    me" in out(run("//a", stdin=doc))

    def test_special_characters_are_escaped_in_serialization(self):
        doc = "<r><a>a &amp; b</a></r>"
        assert "&amp;" in out(run("//a", stdin=doc))

    def test_namespace_declaration_retained(self):
        doc = '<r xmlns:n="http://example.com/n"><n:item>x</n:item></r>'
        o = out(run("//*[local-name()='item']", stdin=doc))
        assert "http://example.com/n" in o

    # Retired and reversed by the json/union spec: "A union with mixed result
    # types is written as text results." T4's XML-branch guess no longer
    # applies; see the T26 annotation and T42.
    def test_union_of_node_and_text_is_written_as_text(self):
        doc = "<r><a>1</a><b>2</b></r>"
        o = out(run("//a | //b/text()", stdin=doc))
        assert o == "1\n2"


# Spec: "No-match output: write nothing to stdout/stderr."
# Context: an empty result set produces completely silent success.


class TestNoMatchOutput:
    @pytest.mark.parametrize(
        "query",
        [
            "//nope",
            "//nope/text()",
            "//a/@missing",
            "/root/zzz",
            "//a[99]",
            "//book[@id='nothing']",
        ],
    )
    def test_no_match_is_silent_and_successful(self, query):
        proc = run(query, stdin=FLAT if query.startswith(("//a", "//nope", "/root")) else CATALOG)
        assert proc.returncode == 0
        assert proc.stdout == b""
        assert proc.stderr == b""

    def test_no_match_writes_nothing_not_even_a_newline(self):
        proc = run("//nope", stdin=FLAT)
        assert proc.stdout == b""

    def test_no_match_stderr_is_empty(self):
        proc = run("//nope", stdin=FLAT)
        assert proc.stderr == b""

    def test_successful_match_writes_nothing_to_stderr(self):
        proc = run("//a/text()", stdin=FLAT)
        assert proc.stderr == b""


# ===========================================================================
# Errors
# ===========================================================================

# Spec: "Invalid XPath: stderr message, exit code `1`; message should reference
# `xpath`."


class TestInvalidXPath:
    BAD_QUERIES = [
        "//[",
        "///",
        "//a[",
        "not-a-function()",
        "//a[@x=]",
        "..//**",
        "@@",
        "1 +",
        "//a/'",
    ]

    @pytest.mark.parametrize("query", BAD_QUERIES)
    def test_invalid_xpath_exits_one(self, query):
        assert run(query, stdin=FLAT).returncode == 1

    @pytest.mark.parametrize("query", BAD_QUERIES)
    def test_invalid_xpath_message_mentions_xpath(self, query):
        proc = run(query, stdin=FLAT)
        assert "xpath" in err(proc).lower()

    @pytest.mark.parametrize("query", BAD_QUERIES)
    def test_invalid_xpath_writes_to_stderr_not_stdout(self, query):
        proc = run(query, stdin=FLAT)
        assert proc.stderr != b""
        assert proc.stdout == b""

    def test_empty_query_string_is_an_xpath_error(self):
        proc = run("", stdin=FLAT)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_unknown_function_is_an_xpath_error(self):
        proc = run("//a[bogus-fn(.)]", stdin=FLAT)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_xpath_error_is_reported_even_though_xml_is_valid(self):
        proc = run("//[", stdin=CATALOG)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_no_traceback_leaks_to_stderr(self):
        proc = run("//[", stdin=FLAT)
        assert "Traceback" not in err(proc)


# Spec: "Malformed/empty XML input: stderr message, exit code `1`; message
# should reference `xml`/`parse`."
# Context: parse failure of stdin, including no input at all. See T1.


class TestMalformedOrEmptyXml:
    MALFORMED = [
        "<root><child></root>",
        "<root>",
        "</root>",
        "<root><a></b></root>",
        "not xml at all",
        "<root attr=unquoted/>",
        "<1invalid/>",
        "<root>&undefined;</root>",
        # NOTE: `{"json": true}` used to belong here. The JSON spec supersedes
        # that: a top-level JSON object is now valid input. See T1's annotation.
        '{"json": true,}',
    ]

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_xml_exits_one(self, doc):
        assert run("//a", stdin=doc).returncode == 1

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_xml_message_mentions_xml_or_parse(self, doc):
        msg = err(run("//a", stdin=doc)).lower()
        assert "xml" in msg or "parse" in msg

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_xml_writes_nothing_to_stdout(self, doc):
        assert run("//a", stdin=doc).stdout == b""

    @pytest.mark.parametrize("doc", ["", "   ", "\n\n", "\t \n"])
    def test_empty_input_exits_one_with_message(self, doc):
        proc = run("//a", stdin=doc)
        assert proc.returncode == 1
        msg = err(proc).lower()
        assert "xml" in msg or "parse" in msg

    def test_empty_input_writes_nothing_to_stdout(self):
        assert run("//a", stdin="").stdout == b""

    def test_malformed_xml_no_traceback(self):
        assert "Traceback" not in err(run("//a", stdin="<root>"))

    def test_multiple_root_elements_is_malformed(self):
        proc = run("//a", stdin="<a/><b/>")
        assert proc.returncode == 1

    def test_valid_xml_with_leading_whitespace_is_accepted(self):
        proc = run("//a/text()", stdin="\n\n  <root><a>ok</a></root>\n")
        assert proc.returncode == 0
        assert out(proc) == "ok"

    def test_xml_with_doctype_is_accepted(self):
        doc = '<?xml version="1.0"?><!DOCTYPE root><root><a>ok</a></root>'
        proc = run("//a/text()", stdin=doc)
        assert proc.returncode == 0
        assert out(proc) == "ok"

    def test_comment_before_root_is_accepted(self):
        proc = run("//a/text()", stdin="<!-- hi --><root><a>ok</a></root>")
        assert proc.returncode == 0
        assert out(proc) == "ok"


# Spec: error precedence context - both an invalid query and bad XML.
# Context: not stated explicitly; either message is acceptable, but the exit
# code must be 1 and stdout must stay empty.


class TestCombinedErrors:
    def test_bad_xml_and_bad_xpath_exits_one(self):
        proc = run("//[", stdin="<root>")
        assert proc.returncode == 1
        assert proc.stdout == b""
        assert proc.stderr != b""


# ===========================================================================
# End-to-end sanity over the whole spec
# ===========================================================================


class TestEndToEnd:
    def test_text_attribute_and_node_modes_on_one_document(self):
        assert out(run("//title/text()", stdin=CATALOG)) == "XPath Basics\nXPath Avance"
        assert out(run("//book/@lang", stdin=CATALOG)) == "en\nfr"
        assert "<title>XPath Basics</title>" in out(run("//book", stdin=CATALOG))
        assert run("//missing", stdin=CATALOG).stdout == b""

    def test_repeated_invocations_are_deterministic(self):
        first = run("//title/text()", stdin=CATALOG)
        second = run("//title/text()", stdin=CATALOG)
        assert first.stdout == second.stdout
        assert first.returncode == second.returncode == 0


# ===========================================================================
# CSS Selectors and Text Extraction  (follow-up spec)
# ===========================================================================

# Shared fixtures for the CSS/text spec ------------------------------------

# Compact (no indentation) so text-node counts are exactly predictable.
MIXED = "<r><p>Hello <b>bold</b> world</p></r>"

TWOP = "<r><p>one</p><p>two</p></r>"

PAGE = """<html>
  <body>
    <div class="post first" id="p1">
      <h2>First   title</h2>
      <p>Hello <b>bold</b> world</p>
    </div>
    <div class="post" id="p2">
      <h2>Second title</h2>
      <p>Bye</p>
    </div>
    <span class="tag" data-k="a">alpha</span>
    <span class="tag" data-k="b">beta</span>
  </body>
</html>
"""

CASEDOC = "<Root><Item>upper</Item><item>lower</item></Root>"


# ---------------------------------------------------------------------------
# CLI Additions
# ---------------------------------------------------------------------------

# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: a new flag that switches the QUERY positional from XPath 1.0 to CSS.


class TestCssFlag:
    def test_css_flag_is_accepted(self):
        proc = run("--css", "p", stdin=TWOP)
        assert proc.returncode == 0

    def test_query_is_read_as_css_not_xpath(self):
        # "p" is a valid CSS selector; as XPath it would be a relative child
        # step off the root and match nothing here.
        assert "<p>one</p>" in out(run("--css", "p", stdin=TWOP))

    def test_without_css_flag_the_same_query_is_xpath(self):
        # `#p2` is an id selector in CSS and a syntax error in XPath.
        assert run("--css", "#p2", stdin=PAGE).returncode == 0
        assert run("#p2", stdin=PAGE).returncode == 1

    def test_css_selector_matches_anywhere_in_the_document(self):
        # A bare type selector is document-wide, not root-anchored.
        assert "<h2>" in out(run("--css", "h2", stdin=PAGE))

    def test_css_class_selector(self):
        o = out(run("--css", ".tag", stdin=PAGE))
        assert "alpha" in o

    def test_css_class_selector_matches_one_token_of_many(self):
        o = out(run("--css", ".first", stdin=PAGE))
        assert 'id="p1"' in o

    def test_css_id_selector(self):
        o = out(run("--css", "#p2", stdin=PAGE))
        assert "Second title" in o

    def test_css_attribute_selector(self):
        o = out(run("--css", "span[data-k=b]", stdin=PAGE))
        assert "beta" in o

    def test_css_descendant_combinator(self):
        o = out(run("--css", "div p", stdin=PAGE))
        assert "<p>" in o and "Hello" in o

    def test_css_child_combinator(self):
        o = out(run("--css", "body > span", stdin=PAGE))
        assert "alpha" in o

    def test_css_structural_pseudo_class(self):
        o = out(run("--css", "div:nth-of-type(2)", stdin=PAGE))
        assert "Second title" in o

    def test_css_comma_group_of_plain_selectors(self):
        proc = run("--css", "h2, span", stdin=PAGE)
        assert proc.returncode == 0

    # T16: XML-flavoured (case-sensitive) translation.
    def test_css_type_selector_is_case_sensitive(self):
        assert "upper" in out(run("--css", "Item", stdin=CASEDOC))

    def test_css_type_selector_does_not_case_fold(self):
        o = out(run("--css", "item", stdin=CASEDOC))
        assert "lower" in o
        assert "upper" not in o

    def test_css_no_match_is_silent_success(self):
        proc = run("--css", "nosuchtag", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""
        assert proc.stderr == b""

    def test_css_still_accepts_the_infile_positional(self, tmp_path):
        # The file-input spec makes INFILE a real, opened path.
        doc = tmp_path / "in.xml"
        doc.write_text(TWOP, encoding="utf-8")
        proc = run("--css", "p", str(doc))
        assert proc.returncode == 0


# Spec: "`-t`, `--text`: direct text extraction from matched elements, one per
# element."
# Context: a post-processing modifier over the matched element set. Both spellings
# name the same flag. "one per element" fixes the output granularity. See T9, T11.


class TestTextFlag:
    def test_short_and_long_spellings_both_exist(self):
        assert out(run("-t", "//p", stdin=TWOP)) == out(run("--text", "//p", stdin=TWOP))

    def test_direct_text_of_a_single_element(self):
        assert out(run("--css", "-t", "p", stdin="<r><p>one</p></r>")) == "one"

    def test_one_line_per_matched_element(self):
        assert out(run("--css", "-t", "p", stdin=TWOP)) == "one\ntwo"

    def test_every_match_is_emitted_not_just_the_first(self):
        o = out(run("--css", "-t", "span", stdin=PAGE))
        assert o == "alpha\nbeta"

    # T9: "direct text" is every direct text-node child, joined, not just el.text.
    def test_mixed_content_joins_direct_text_nodes_into_one_line(self):
        assert out(run("--css", "-t", "p", stdin=MIXED)) == "Hello world"

    def test_direct_text_excludes_descendant_element_text(self):
        assert "bold" not in out(run("--css", "-t", "p", stdin=MIXED))

    def test_element_with_no_direct_text_yields_an_empty_line(self):
        # T2/T14: results that normalize to empty keep their slot.
        doc = "<r><p>x</p><p><b>y</b></p><p>z</p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "x\n\nz"

    def test_text_flag_output_has_no_trailing_newline(self):
        assert not out(run("--css", "-t", "p", stdin=TWOP)).endswith("\n")

    # T11: the flag is not restricted to CSS mode.
    def test_text_flag_works_with_an_xpath_query(self):
        assert out(run("-t", "//p", stdin=TWOP)) == "one\ntwo"

    def test_text_flag_with_xpath_mixed_content(self):
        assert out(run("-t", "//p", stdin=MIXED)) == "Hello world"

    def test_text_flag_replaces_xml_node_output(self):
        o = out(run("--css", "-t", "p", stdin=TWOP))
        assert "<p>" not in o

    def test_text_flag_on_no_match_is_silent(self):
        proc = run("--css", "-t", "nosuchtag", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""
        assert proc.stderr == b""

    def test_text_flag_on_root_element(self):
        assert out(run("-t", "/r", stdin=TWOP)) == ""


# Spec: "`--text-all`: descendant text extraction from matched elements, one per
# element."
# Context: same shape as --text but the whole subtree's text, still collapsed to a
# single line per matched element.


class TestTextAllFlag:
    def test_descendant_text_of_a_single_element(self):
        assert out(run("--css", "--text-all", "p", stdin=MIXED)) == "Hello bold world"

    def test_one_line_per_matched_element(self):
        assert out(run("--css", "--text-all", "p", stdin=TWOP)) == "one\ntwo"

    def test_includes_nested_element_text(self):
        doc = "<r><d>a<e>b<f>c</f></e></d></r>"
        assert out(run("--css", "--text-all", "d", stdin=doc)) == "abc"

    def test_deep_subtree_is_still_a_single_line_per_element(self):
        o = out(run("--css", "--text-all", "div", stdin=PAGE))
        assert o.count("\n") == 1

    def test_descendant_text_of_indented_source_is_collapsed(self):
        o = out(run("--css", "--text-all", "div", stdin=PAGE))
        assert o.split("\n")[0] == "First title Hello bold world"

    def test_text_all_works_with_an_xpath_query(self):
        assert out(run("--text-all", "//p", stdin=MIXED)) == "Hello bold world"

    def test_text_all_output_has_no_trailing_newline(self):
        assert not out(run("--css", "--text-all", "p", stdin=TWOP)).endswith("\n")

    def test_text_all_on_no_match_is_silent(self):
        proc = run("--css", "--text-all", "nosuchtag", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""

    def test_empty_element_yields_an_empty_line(self):
        doc = "<r><p>x</p><p/></r>"
        assert out(run("--css", "--text-all", "p", stdin=doc)) == "x\n"


# ---------------------------------------------------------------------------
# CSS Query Mode
# ---------------------------------------------------------------------------

# Spec: "Define custom `::text` pseudo-element: `selector::text` returns direct
# text"
# Context: no whitespace before `::text` - the pseudo-element attaches to the
# compound selector, selecting that element's own text nodes. See T8.


class TestDirectTextPseudoElement:
    def test_direct_text_of_a_matched_element(self):
        assert out(run("--css", "p::text", stdin="<r><p>one</p></r>")) == "one"

    def test_direct_text_across_several_matches(self):
        assert out(run("--css", "p::text", stdin=TWOP)) == "one\ntwo"

    # T8: `::text` is the `/text()` step, so mixed content is one line per node.
    def test_mixed_content_yields_one_line_per_direct_text_node(self):
        assert out(run("--css", "p::text", stdin=MIXED)) == "Hello\nworld"

    def test_direct_text_excludes_descendant_element_text(self):
        assert "bold" not in out(run("--css", "p::text", stdin=MIXED))

    def test_direct_text_on_a_compound_selector(self):
        assert out(run("--css", "span.tag::text", stdin=PAGE)) == "alpha\nbeta"

    def test_direct_text_on_an_id_selector(self):
        assert out(run("--css", "#p2 h2::text", stdin=PAGE)) == "Second title"

    def test_direct_text_of_an_element_with_only_children_is_empty(self):
        assert out(run("--css", "p::text", stdin="<r><p><b>y</b></p></r>") ) == ""

    def test_direct_text_output_is_not_xml(self):
        assert "<p>" not in out(run("--css", "p::text", stdin=TWOP))

    def test_direct_text_no_match_is_silent(self):
        proc = run("--css", "nosuchtag::text", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""
        assert proc.stderr == b""

    def test_universal_direct_text(self):
        assert out(run("--css", "*::text", stdin="<r><p>one</p></r>")) == "one"

    def test_bare_double_colon_text_is_a_valid_query(self):
        assert out(run("--css", "::text", stdin="<r><p>one</p></r>")) == "one"


# Spec: "`selector ::text` returns all descendant text nodes (one text node per
# line)."
# Context: the space makes `::text` a descendant of the selector, so every text
# node in the subtree is selected, each on its own output line. See T8, T14.


class TestDescendantTextPseudoElement:
    def test_descendant_text_includes_nested_element_text(self):
        assert out(run("--css", "p ::text", stdin=MIXED)) == "Hello\nbold\nworld"

    def test_one_line_per_text_node_not_per_element(self):
        assert out(run("--css", "p ::text", stdin=MIXED)).count("\n") == 2

    def test_descendant_text_includes_the_elements_own_direct_text(self):
        doc = "<r><d>a<e>b</e></d></r>"
        assert out(run("--css", "d ::text", stdin=doc)) == "a\nb"

    def test_descendant_text_is_document_order(self):
        doc = "<r><d>a<e>b</e>c<f>d</f></d></r>"
        assert out(run("--css", "d ::text", stdin=doc)) == "a\nb\nc\nd"

    def test_space_before_pseudo_element_changes_the_result(self):
        assert out(run("--css", "p ::text", stdin=MIXED)) != out(
            run("--css", "p::text", stdin=MIXED)
        )

    def test_descendant_text_over_several_matches(self):
        doc = "<r><d>a<e>b</e></d><d>c</d></r>"
        assert out(run("--css", "d ::text", stdin=doc)) == "a\nb\nc"

    # T14: whitespace-only text nodes are kept and normalize to empty lines.
    def test_indentation_text_nodes_are_kept_as_empty_lines(self):
        doc = "<r>\n  <d>\n    <e>b</e>\n  </d>\n</r>"
        assert out(run("--css", "d ::text", stdin=doc)) == "\nb\n"

    def test_descendant_text_no_match_is_silent(self):
        proc = run("--css", "nosuchtag ::text", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""

    def test_descendant_text_after_a_multi_step_selector(self):
        doc = "<r><d><e><f>deep</f></e></d></r>"
        assert out(run("--css", "d e ::text", stdin=doc)) == "deep"

    def test_descendant_text_output_is_not_xml(self):
        assert "<b>" not in out(run("--css", "p ::text", stdin=MIXED))


# Spec: "Comma-separated selectors are supported for `::text` queries when all
# selectors use the same `::text` mode."
# Context: a group of selectors, each carrying the same flavour of ::text, is a
# valid query; results come back in document order.


class TestCommaSeparatedTextSelectors:
    def test_two_direct_text_selectors(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("--css", "a::text, b::text", stdin=doc)) == "1\n2"

    def test_two_descendant_text_selectors(self):
        doc = "<r><a>1<i>x</i></a><b>2</b></r>"
        assert out(run("--css", "a ::text, b ::text", stdin=doc)) == "1\nx\n2"

    def test_three_direct_text_selectors(self):
        doc = "<r><a>1</a><b>2</b><c>3</c></r>"
        assert out(run("--css", "a::text, b::text, c::text", stdin=doc)) == "1\n2\n3"

    def test_results_are_in_document_order_not_selector_order(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("--css", "b::text, a::text", stdin=doc)) == "1\n2"

    def test_whitespace_around_the_comma_is_tolerated(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("--css", "a::text,b::text", stdin=doc)) == "1\n2"

    def test_comma_group_with_compound_selectors(self):
        assert out(run("--css", "h2::text, .tag::text", stdin=PAGE)) == (
            "First title\nSecond title\nalpha\nbeta"
        )

    def test_comma_group_exit_code_is_zero(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert run("--css", "a::text, b::text", stdin=doc).returncode == 0

    def test_comma_group_with_no_matches_is_silent(self):
        proc = run("--css", "zz::text, yy::text", stdin=PAGE)
        assert proc.returncode == 0
        assert proc.stdout == b""


# Spec: "Mixing direct and descendant `::text` modes in one comma-separated CSS
# query is invalid (stderr message, exit code `1`)."
# Context: the group must be homogeneous. See T10 for the treatment of a group
# that mixes a ::text selector with a plain one.


class TestMixedTextModesAreInvalid:
    @pytest.mark.parametrize(
        "query",
        [
            "a::text, b ::text",
            "a ::text, b::text",
            "a::text, b::text, c ::text",
            "div p::text, div ::text",
        ],
    )
    def test_mixed_modes_exit_1(self, query):
        assert run("--css", query, stdin=PAGE).returncode == 1

    def test_mixed_modes_write_a_message_to_stderr(self):
        proc = run("--css", "a::text, b ::text", stdin=PAGE)
        assert proc.stderr != b""

    def test_mixed_modes_write_nothing_to_stdout(self):
        proc = run("--css", "a::text, b ::text", stdin=PAGE)
        assert proc.stdout == b""

    def test_mixed_modes_message_mentions_text(self):
        proc = run("--css", "a::text, b ::text", stdin=PAGE)
        assert "::text" in err(proc)

    def test_mixed_modes_error_even_when_nothing_would_match(self):
        proc = run("--css", "zz::text, yy ::text", stdin=PAGE)
        assert proc.returncode == 1

    def test_mixed_modes_error_is_unaffected_by_text_flags(self):
        proc = run("--css", "-t", "a::text, b ::text", stdin=PAGE)
        assert proc.returncode == 1

    # T10: a plain selector is a third, different "mode".
    def test_text_selector_mixed_with_plain_selector_is_invalid(self):
        proc = run("--css", "a::text, b", stdin=PAGE)
        assert proc.returncode == 1
        assert proc.stderr != b""

    def test_plain_selector_mixed_with_descendant_text_is_invalid(self):
        proc = run("--css", "a, b ::text", stdin=PAGE)
        assert proc.returncode == 1

    def test_homogeneous_plain_group_is_still_fine(self):
        assert run("--css", "a, b", stdin=PAGE).returncode == 0


# Spec: "In CSS mode without text extraction, return XML node output with
# pretty-print serialization."
# Context: CSS mode reuses the established XML node output path. See T5, T12.


class TestCssXmlNodeOutput:
    def test_matched_element_is_serialized_as_xml(self):
        o = out(run("--css", "p", stdin=TWOP))
        assert "<p>one</p>" in o

    def test_output_is_not_the_string_value(self):
        assert out(run("--css", "p", stdin=TWOP)).strip() != "one"

    # T12: the first-node-only rule carries over from the XPath node output mode.
    def test_only_the_first_match_is_serialized(self):
        o = out(run("--css", "p", stdin=TWOP))
        assert "one" in o
        assert "two" not in o

    def test_attributes_are_serialized(self):
        o = out(run("--css", "div", stdin=PAGE))
        assert 'id="p1"' in o

    def test_descendants_are_serialized(self):
        o = out(run("--css", "div", stdin=PAGE))
        assert "<h2>" in o and "<p>" in o

    def test_pretty_print_indents_children(self):
        o = out(run("--css", "div", stdin=PAGE))
        lines = o.split("\n")
        assert lines[0].startswith("<div")
        assert next(ln for ln in lines if "<h2>" in ln).startswith(" ")

    def test_pretty_print_reindents_from_column_zero(self):
        # T5: the selected node's closing tag carries no source indentation.
        o = out(run("--css", "div", stdin=PAGE)).rstrip("\n")
        assert o.split("\n")[-1] == "</div>"

    def test_pretty_print_of_single_line_source(self):
        doc = "<r><outer><inner>v</inner></outer></r>"
        o = out(run("--css", "outer", stdin=doc))
        assert o.count("\n") >= 1
        assert "<inner>v</inner>" in o

    def test_text_whitespace_is_not_collapsed_in_node_output(self):
        doc = "<r><p>keep    me</p></r>"
        assert "keep    me" in out(run("--css", "p", stdin=doc))

    def test_css_node_output_matches_equivalent_xpath_node_output(self):
        assert out(run("--css", "p", stdin=TWOP)) == out(run("//p", stdin=TWOP))


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: the query fails to translate. See T15.


class TestInvalidCssSelector:
    @pytest.mark.parametrize(
        "query",
        [
            "div >",
            "a[",
            ">>>",
            "p::",
            "[",
            "a,",
            "div..x",
            "",
        ],
    )
    def test_invalid_selector_exits_1(self, query):
        assert run("--css", query, stdin=PAGE).returncode == 1

    def test_invalid_selector_writes_to_stderr(self):
        proc = run("--css", "div >", stdin=PAGE)
        assert proc.stderr != b""

    def test_invalid_selector_writes_nothing_to_stdout(self):
        proc = run("--css", "div >", stdin=PAGE)
        assert proc.stdout == b""

    def test_invalid_selector_message_mentions_css(self):
        proc = run("--css", "div >", stdin=PAGE)
        assert "css" in err(proc).lower()

    # T15: unsupported-but-well-formed selectors are the same error class.
    @pytest.mark.parametrize("query", ["p::before", "a::first-line", "p::unknown"])
    def test_unknown_pseudo_element_exits_1(self, query):
        assert run("--css", query, stdin=PAGE).returncode == 1

    def test_unknown_pseudo_class_exits_1(self):
        assert run("--css", "a:nosuchclass", stdin=PAGE).returncode == 1

    def test_valid_xpath_is_not_a_valid_css_selector(self):
        proc = run("--css", "//p", stdin=TWOP)
        assert proc.returncode == 1
        assert proc.stdout == b""

    def test_invalid_css_is_only_an_error_in_css_mode(self):
        # Without --css the same string is just an XPath expression.
        assert run("//p", stdin=TWOP).returncode == 0

    def test_invalid_selector_error_survives_text_flags(self):
        assert run("--css", "-t", "div >", stdin=PAGE).returncode == 1


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

# Spec: "Multi-match text output joins lines with `\n`."
# Context: every text-producing path emits one line per result, newline separated.


class TestTextJoining:
    def test_text_flag_multi_match_joined_with_newline(self):
        assert out(run("--css", "-t", "p", stdin=TWOP)) == "one\ntwo"

    def test_text_all_multi_match_joined_with_newline(self):
        assert out(run("--css", "--text-all", "p", stdin=TWOP)) == "one\ntwo"

    def test_direct_text_pseudo_multi_match_joined_with_newline(self):
        assert out(run("--css", "p::text", stdin=TWOP)) == "one\ntwo"

    def test_descendant_text_pseudo_joined_with_newline(self):
        assert out(run("--css", "p ::text", stdin=MIXED)) == "Hello\nbold\nworld"

    def test_join_uses_lf_not_crlf(self):
        assert b"\r" not in run("--css", "-t", "p", stdin=TWOP).stdout

    def test_single_match_has_no_separator(self):
        assert out(run("--css", "-t", "h2", stdin="<r><h2>x</h2></r>")) == "x"

    def test_no_trailing_newline_on_multi_match(self):
        assert not out(run("--css", "p::text", stdin=TWOP)).endswith("\n")

    def test_line_count_equals_match_count(self):
        o = out(run("--css", "-t", "span", stdin=PAGE))
        assert len(o.split("\n")) == 2


# Spec: "Strip each result and collapse internal whitespace runs to single
# spaces."
# Context: normalization is per result, applied before joining, on every text
# extraction path.


class TestTextNormalization:
    def test_leading_and_trailing_whitespace_stripped_by_text_flag(self):
        doc = "<r><p>   padded   </p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "padded"

    def test_internal_runs_collapsed_by_text_flag(self):
        doc = "<r><p>many     spaces   here</p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "many spaces here"

    def test_newlines_and_tabs_collapse_to_one_space(self):
        doc = "<r><p>a\n\n\tb\r\n  c</p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "a b c"

    def test_normalization_applies_to_text_all(self):
        doc = "<r><d>  a  <e>  b  </e>  c  </d></r>"
        assert out(run("--css", "--text-all", "d", stdin=doc)) == "a b c"

    def test_normalization_applies_to_direct_text_pseudo(self):
        doc = "<r><p>   spaced    out   </p></r>"
        assert out(run("--css", "p::text", stdin=doc)) == "spaced out"

    def test_normalization_applies_to_descendant_text_pseudo(self):
        doc = "<r><d>  a  <e>  b  </e></d></r>"
        assert out(run("--css", "d ::text", stdin=doc)) == "a\nb"

    def test_normalization_is_per_result_then_joined(self):
        doc = "<r><p>  x   y  </p><p> z \n w </p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "x y\nz w"

    def test_indented_source_normalizes_to_one_clean_line(self):
        assert out(run("--css", "--text-all", "h2", stdin=PAGE)) == (
            "First title\nSecond title"
        )

    def test_unicode_text_is_preserved(self):
        doc = "<r><p>café   à la carte</p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "café à la carte"

    def test_entities_are_resolved_then_normalized(self):
        doc = "<r><p>a &amp;   b</p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "a & b"

    def test_cdata_text_is_normalized(self):
        doc = "<r><p><![CDATA[raw   <text>]]></p></r>"
        assert out(run("--css", "-t", "p", stdin=doc)) == "raw <text>"


# ---------------------------------------------------------------------------
# Flag Rules
# ---------------------------------------------------------------------------

# Spec: "If both `--text` and `--text-all` are present, `--text-all` wins."
# Context: the two modifiers are mutually exclusive in effect, not an error.


class TestTextAllWins:
    def test_both_flags_together_are_not_an_error(self):
        assert run("--css", "-t", "--text-all", "p", stdin=MIXED).returncode == 0

    def test_both_flags_give_the_text_all_result(self):
        assert out(run("--css", "-t", "--text-all", "p", stdin=MIXED)) == (
            "Hello bold world"
        )

    def test_both_flags_differ_from_the_text_only_result(self):
        both = out(run("--css", "-t", "--text-all", "p", stdin=MIXED))
        assert both != out(run("--css", "-t", "p", stdin=MIXED))

    def test_order_on_the_command_line_does_not_matter(self):
        a = out(run("--css", "-t", "--text-all", "p", stdin=MIXED))
        b = out(run("--css", "--text-all", "-t", "p", stdin=MIXED))
        assert a == b == out(run("--css", "--text-all", "p", stdin=MIXED))

    def test_long_text_spelling_also_loses(self):
        assert out(run("--css", "--text", "--text-all", "p", stdin=MIXED)) == (
            "Hello bold world"
        )

    def test_both_flags_in_xpath_mode(self):
        assert out(run("-t", "--text-all", "//p", stdin=MIXED)) == "Hello bold world"


# Spec: "If query already extracts text (`text()` or `::text`), `--text` and
# `--text-all` are no-op modifiers."
# Context: nothing is left to extract from, so the flags change nothing. See T13.


class TestTextFlagsAreNoOps:
    def test_text_flag_is_a_noop_on_an_xpath_text_query(self):
        base = out(run("//p/text()", stdin=MIXED))
        assert out(run("-t", "//p/text()", stdin=MIXED)) == base

    def test_text_all_is_a_noop_on_an_xpath_text_query(self):
        base = out(run("//p/text()", stdin=MIXED))
        assert out(run("--text-all", "//p/text()", stdin=MIXED)) == base

    def test_text_flag_is_a_noop_on_a_direct_text_pseudo_query(self):
        base = out(run("--css", "p::text", stdin=MIXED))
        assert out(run("--css", "-t", "p::text", stdin=MIXED)) == base

    def test_text_all_is_a_noop_on_a_direct_text_pseudo_query(self):
        base = out(run("--css", "p::text", stdin=MIXED))
        assert out(run("--css", "--text-all", "p::text", stdin=MIXED)) == base

    def test_text_flag_is_a_noop_on_a_descendant_text_pseudo_query(self):
        base = out(run("--css", "p ::text", stdin=MIXED))
        assert out(run("--css", "-t", "p ::text", stdin=MIXED)) == base

    def test_text_all_is_a_noop_on_a_descendant_text_pseudo_query(self):
        base = out(run("--css", "p ::text", stdin=MIXED))
        assert out(run("--css", "--text-all", "p ::text", stdin=MIXED)) == base

    def test_both_flags_together_are_a_noop_on_a_text_query(self):
        base = out(run("--css", "p ::text", stdin=MIXED))
        assert out(run("--css", "-t", "--text-all", "p ::text", stdin=MIXED)) == base

    def test_noop_keeps_the_exit_code_at_zero(self):
        assert run("--css", "-t", "p::text", stdin=MIXED).returncode == 0

    # T13: the rule generalizes to any result set with nothing to extract from.
    def test_text_flag_is_a_noop_on_an_attribute_query(self):
        assert out(run("-t", "//span/@data-k", stdin=PAGE)) == "a\nb"

    def test_text_flag_is_a_noop_on_a_numeric_result(self):
        assert out(run("-t", "count(//p)", stdin=PAGE)) == "2"

    def test_text_flag_is_a_noop_on_a_string_function_result(self):
        assert out(run("--text-all", "string(//p)", stdin=MIXED)) == "Hello bold world"


# ---------------------------------------------------------------------------
# End-to-end sanity for the CSS/text spec
# ---------------------------------------------------------------------------


class TestCssEndToEnd:
    def test_scrape_titles_with_text_pseudo(self):
        assert out(run("--css", "div h2::text", stdin=PAGE)) == (
            "First title\nSecond title"
        )

    def test_scrape_titles_with_text_flag(self):
        assert out(run("--css", "-t", "div h2", stdin=PAGE)) == (
            "First title\nSecond title"
        )

    def test_scrape_post_bodies_with_text_all(self):
        assert out(run("--css", "--text-all", "div p", stdin=PAGE)) == (
            "Hello bold world\nBye"
        )

    def test_node_output_then_text_output_of_the_same_selector(self):
        node = out(run("--css", "span.tag", stdin=PAGE))
        text = out(run("--css", "span.tag::text", stdin=PAGE))
        assert "<span" in node and "<span" not in text

    def test_unmatched_selector_everywhere_is_silent(self):
        for extra in ([], ["-t"], ["--text-all"]):
            proc = run("--css", *extra, "nope", stdin=PAGE)
            assert proc.returncode == 0
            assert proc.stdout == b""
            assert proc.stderr == b""

    def test_malformed_xml_still_errors_in_css_mode(self):
        proc = run("--css", "p", stdin="<r><p></r>")
        assert proc.returncode == 1
        assert proc.stderr != b""

    def test_empty_input_still_errors_in_css_mode(self):
        proc = run("--css", "p", stdin="")
        assert proc.returncode == 1

    def test_successful_css_run_writes_nothing_to_stderr(self):
        assert run("--css", "p::text", stdin=TWOP).stderr == b""


# ===========================================================================
# JSON Input and Auto-Detection  (follow-up spec)
# ===========================================================================

# Shared fixtures for the JSON spec -----------------------------------------

JSON_OBJ = '{"name": "Ada", "age": 36, "active": true}'
JSON_ARR = '[1, 2, 3]'
JSON_NESTED = '{"user": {"id": 7, "tags": ["x", "y"]}, "ok": false, "note": null}'


def json_root(text):
    """Serialize the whole converted document by selecting `/root`."""
    return out(run("/root", stdin=text))


# ---------------------------------------------------------------------------
# Input Auto-Detection
# ---------------------------------------------------------------------------

# Spec: "Auto-detect stdin as JSON object/array or XML/HTML."
# Context: no flag is involved - the tool inspects stdin itself and picks the
# parser. A JSON object or a JSON array both qualify as JSON input. See T17.


class TestJsonAutoDetection:
    def test_json_object_is_detected_and_queryable(self):
        assert out(run("//name", stdin=JSON_OBJ)).strip() != ""

    def test_json_array_is_detected_and_queryable(self):
        assert out(run("count(//item)", stdin=JSON_ARR)) == "3"

    def test_detection_needs_no_flag(self):
        proc = run("/root/name/text()", stdin=JSON_OBJ)
        assert proc.returncode == 0
        assert out(proc) == "Ada"

    def test_xml_input_is_still_detected_as_xml(self):
        assert out(run("//b/text()", stdin=FLAT)) == "three"

    def test_leading_whitespace_before_json_still_detects(self):
        assert out(run("//a/text()", stdin='\n\t  {"a": 1}  \n')) == "1"

    def test_json_detection_works_in_css_mode(self):
        assert out(run("--css", "name::text", stdin=JSON_OBJ)) == "Ada"

    def test_json_detection_works_with_text_flag(self):
        assert out(run("-t", "//name", stdin=JSON_OBJ)) == "Ada"

    def test_empty_json_object_is_json(self):
        assert "<root" in json_root("{}")

    def test_empty_json_array_is_json(self):
        assert "<root" in json_root("[]")

    # T25: the converted tree is an ordinary XML tree for every query mode.
    def test_type_attribute_is_visible_to_queries(self):
        assert out(run("//age/@type", stdin=JSON_OBJ)) == "int"


# Spec: "Top-level JSON primitives are not accepted as JSON input for this
# mode; they fall back to XML parsing."
# Context: a bare string, number, boolean or null at top level is valid JSON but
# is rejected as JSON *input*; the bytes go to the XML parser instead, which
# then fails on them. See T24.


class TestTopLevelPrimitivesFallBack:
    @pytest.mark.parametrize(
        "primitive", ['"hello"', "42", "1.5", "true", "false", "null", "-7"]
    )
    def test_top_level_primitive_is_not_json_input(self, primitive):
        proc = run("/root", stdin=primitive)
        assert proc.returncode == 1
        assert proc.stdout == b""

    @pytest.mark.parametrize("primitive", ['"hello"', "42", "true", "null"])
    def test_fallback_error_mentions_xml_parsing(self, primitive):
        e = err(run("/root", stdin=primitive)).lower()
        assert "xml" in e or "parse" in e

    def test_top_level_primitive_never_produces_a_root_element(self):
        assert b"root" not in run("//*", stdin="42").stdout


# Spec: "Input that fails JSON detection is parsed as XML/HTML."
# Context: anything not recognized as a JSON object/array - malformed JSON,
# XML, junk - is handed to the XML parser, keeping the earlier XML behavior.


class TestNonJsonFallsBackToXml:
    def test_malformed_json_object_goes_to_the_xml_parser(self):
        proc = run("/root", stdin='{"a": 1,}')
        assert proc.returncode == 1
        e = err(proc).lower()
        assert "xml" in e or "parse" in e

    def test_unterminated_json_goes_to_the_xml_parser(self):
        proc = run("/root", stdin='{"a": 1')
        assert proc.returncode == 1

    def test_json_like_prefix_with_trailing_junk_is_not_json(self):
        proc = run("/root", stdin='{"a": 1} trailing')
        assert proc.returncode == 1

    def test_well_formed_xml_is_unaffected_by_json_detection(self):
        assert out(run("//title/text()", stdin=CATALOG)).splitlines()[0] == (
            "XPath Basics"
        )

    def test_empty_input_still_errors_as_xml(self):
        proc = run("/root", stdin="")
        assert proc.returncode == 1
        assert "xml" in err(proc).lower() or "parse" in err(proc).lower()

    def test_non_utf8_bytes_fall_back_to_xml(self):
        doc = '<?xml version="1.0" encoding="ISO-8859-1"?><r><a>caf\xe9</a></r>'
        proc = run("//a/text()", stdin=doc.encode("iso-8859-1"))
        assert proc.returncode == 0
        assert out(proc) == "café"


# ---------------------------------------------------------------------------
# JSON-to-XML Contract
# ---------------------------------------------------------------------------

# Spec: "Wrap converted documents in `<root>`."
# Context: the converted document always has exactly one root element named
# `root`, whatever the JSON top-level container was.


class TestRootWrapper:
    def test_object_document_root_is_root(self):
        assert out(run("name(/*)", stdin=JSON_OBJ)) == "root"

    def test_array_document_root_is_root(self):
        assert out(run("name(/*)", stdin=JSON_ARR)) == "root"

    def test_root_is_the_only_top_level_element(self):
        assert out(run("count(/*)", stdin=JSON_NESTED)) == "1"

    def test_root_serializes_as_the_outermost_tag(self):
        o = json_root(JSON_OBJ)
        assert o.startswith("<root")
        assert o.rstrip("\n").endswith("</root>")


# Spec: "`<root>` must not include `type`."
# Context: the type attribute is carried by converted elements, but the wrapper
# is exempt - even though the top level is itself a dict or a list.


class TestRootHasNoType:
    def test_root_has_no_type_attribute_for_objects(self):
        assert out(run("/root/@type", stdin=JSON_OBJ)) == ""

    def test_root_has_no_type_attribute_for_arrays(self):
        assert out(run("/root/@type", stdin=JSON_ARR)) == ""

    def test_root_has_no_attributes_at_all(self):
        assert out(run("count(/root/@*)", stdin=JSON_NESTED)) == "0"

    def test_serialized_root_tag_shows_no_type(self):
        first_line = json_root(JSON_OBJ).split("\n")[0]
        assert "type=" not in first_line


# Spec: "For top-level objects: keys become direct child elements."
# Context: one child element of <root> per key, at depth 1.


class TestTopLevelObjectKeys:
    def test_each_key_becomes_a_child_of_root(self):
        assert out(run("count(/root/*)", stdin=JSON_OBJ)) == "3"

    def test_children_are_named_after_the_keys(self):
        assert out(run("name(/root/*[1])", stdin=JSON_OBJ)) == "name"

    def test_keys_are_direct_children_not_grandchildren(self):
        assert out(run("count(/root/age)", stdin=JSON_OBJ)) == "1"

    def test_no_item_wrapper_for_objects(self):
        assert out(run("count(//item)", stdin=JSON_OBJ)) == "0"

    def test_nested_object_keys_become_children_of_that_key(self):
        assert out(run("/root/user/id/text()", stdin=JSON_NESTED)) == "7"


# Spec: "For top-level arrays: each entry becomes an `<item>` child of
# `<root>`."
# Context: array entries have no key to name them, so they all become <item>.
# See T18 for nested arrays.


class TestTopLevelArrayItems:
    def test_one_item_per_entry(self):
        assert out(run("count(/root/item)", stdin=JSON_ARR)) == "3"

    def test_items_are_direct_children_of_root(self):
        assert out(run("count(/root/*)", stdin=JSON_ARR)) == "3"

    def test_item_order_matches_array_order(self):
        assert out(run("-t", "/root/item", stdin=JSON_ARR)) == "1\n2\n3"

    def test_items_of_mixed_types(self):
        o = out(run("-t", "/root/item", stdin='["a", 2, true, null]'))
        assert o == "a\n2\ntrue\n"

    def test_empty_array_has_no_items(self):
        assert out(run("count(/root/item)", stdin="[]")) == "0"

    def test_array_of_objects_nests_under_item(self):
        doc = '[{"a": 1}, {"a": 2}]'
        assert out(run("-t", "/root/item/a", stdin=doc)) == "1\n2"

    # T18: nested arrays use <item> as well.
    def test_nested_array_entries_also_become_item(self):
        assert out(run("-t", "/root/tags/item", stdin='{"tags": ["x","y"]}')) == "x\ny"

    def test_array_of_arrays_nests_item_in_item(self):
        assert out(run("-t", "/root/item/item", stdin="[[1],[2]]")) == "1\n2"


# Spec: "Object keys become element tag names (case preserved)."
# Context: no lower-casing or normalization of key text; the tag is the key
# verbatim, so queries against it are case-sensitive.


class TestKeyCasePreserved:
    def test_mixed_case_key_keeps_its_case(self):
        assert out(run("name(/root/*[1])", stdin='{"MyKey": 1}')) == "MyKey"

    def test_lowercased_query_does_not_match_a_mixed_case_key(self):
        assert out(run("//mykey", stdin='{"MyKey": 1}')) == ""

    def test_keys_differing_only_in_case_are_distinct_elements(self):
        doc = '{"k": 1, "K": 2}'
        assert out(run("/root/k/text()", stdin=doc)) == "1"
        assert out(run("/root/K/text()", stdin=doc)) == "2"

    def test_underscore_and_dash_and_dot_keys_are_kept(self):
        doc = '{"a_b": 1, "a-b": 2, "a.b": 3}'
        assert out(run("-t", "/root/*", stdin=doc)) == "1\n2\n3"


# Spec: "Primitive values map to element text: booleans as `true`/`false`,
# numbers as minimal string form, null as empty (no self-closing tags)."
# Examples: "1 -> \"1\"", "1.0 -> \"1\"", "1.50 -> \"1.5\"",
# "0.00012 -> \"0.00012\"".
# Context: the element's text is the rendered primitive. See T20, T21.


class TestPrimitiveText:
    def test_string_value_becomes_text(self):
        assert out(run("/root/a/text()", stdin='{"a": "hi"}')) == "hi"

    def test_true_renders_as_lowercase_true(self):
        assert out(run("/root/a/text()", stdin='{"a": true}')) == "true"

    def test_false_renders_as_lowercase_false(self):
        assert out(run("/root/a/text()", stdin='{"a": false}')) == "false"

    @pytest.mark.parametrize(
        "value,text",
        [
            ("1", "1"),
            ("1.0", "1"),
            ("1.50", "1.5"),
            ("0.00012", "0.00012"),
            ("0", "0"),
            ("-3", "-3"),
            ("-2.5", "-2.5"),
            ("100", "100"),
            ("2.0", "2"),
            ("12345678901234567890", "12345678901234567890"),
        ],
    )
    def test_number_minimal_string_form(self, value, text):
        assert out(run("/root/a/text()", stdin='{"a": %s}' % value)) == text

    # T21: exponent-notation input is normalized through the float value.
    def test_exponent_input_renders_as_a_plain_integer(self):
        assert out(run("/root/a/text()", stdin='{"a": 1e2}')) == "100"

    def test_null_has_empty_text(self):
        assert out(run("/root/a/text()", stdin='{"a": null}')) == ""

    def test_null_element_exists_even_though_it_is_empty(self):
        assert out(run("count(/root/a)", stdin='{"a": null}')) == "1"

    def test_null_is_not_self_closing_in_serialization(self):
        o = json_root('{"a": null}')
        assert '<a type="null"></a>' in o
        assert "<a type=\"null\"/>" not in o

    # T22: the no-self-closing rule is applied to every empty element.
    def test_empty_string_is_not_self_closing(self):
        o = json_root('{"a": ""}')
        assert "></a>" in o and "/>" not in o

    def test_empty_dict_is_not_self_closing(self):
        assert "/>" not in json_root('{"a": {}}')

    def test_empty_list_is_not_self_closing(self):
        assert "/>" not in json_root('{"a": []}')

    def test_string_special_characters_are_escaped(self):
        o = json_root('{"a": "x & <y>"}')
        assert "&amp;" in o and "&lt;y&gt;" in o

    def test_unicode_string_value_survives(self):
        assert out(run("/root/a/text()", stdin='{"a": "café"}')) == "café"

    def test_whitespace_in_string_value_is_preserved_in_xml_output(self):
        assert "keep    me" in json_root('{"a": "keep    me"}')

    def test_container_elements_have_no_own_text(self):
        assert out(run("string(/root/a/text())", stdin='{"a": {"b": 1}}')) == ""


# Spec: "Every converted element except `<root>` carries `type` in: `str`,
# `int`, `float`, `bool`, `dict`, `list`, `null`."
# Context: exactly one of the seven names, on every element below <root>,
# including <item> elements and container elements.


class TestTypeAttribute:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ('"s"', "str"),
            ('""', "str"),
            ("7", "int"),
            ("-7", "int"),
            ("0", "int"),
            ("1.5", "float"),
            ("1.0", "float"),
            ("true", "bool"),
            ("false", "bool"),
            ("null", "null"),
            ("{}", "dict"),
            ('{"b": 1}', "dict"),
            ("[]", "list"),
            ("[1]", "list"),
        ],
    )
    def test_type_for_each_value_kind(self, value, expected):
        assert out(run("/root/a/@type", stdin='{"a": %s}' % value)) == expected

    def test_booleans_are_bool_not_int(self):
        assert out(run("/root/a/@type", stdin='{"a": true}')) == "bool"

    # T20: JSON numbers written with a fraction or exponent are floats.
    def test_integral_float_is_still_typed_float(self):
        assert out(run("/root/a/@type", stdin='{"a": 2.0}')) == "float"

    def test_exponent_number_is_typed_float(self):
        assert out(run("/root/a/@type", stdin='{"a": 1e2}')) == "float"

    def test_item_elements_carry_type(self):
        assert out(run("-t", "/root/item/@type", stdin='[1, "a", null]')) == (
            "int\nstr\nnull"
        )

    def test_nested_elements_carry_type(self):
        assert out(run("/root/user/tags/@type", stdin=JSON_NESTED)) == "list"

    def test_every_non_root_element_has_a_type(self):
        assert out(run("count(//*) - count(//*[@type]) - 1", stdin=JSON_NESTED)) == "0"

    def test_type_is_one_of_the_seven_names(self):
        names = ["str", "int", "float", "bool", "dict", "list", "null"]
        q = "count(//*[@type][{}])".format(
            " or ".join("@type='{}'".format(n) for n in names)
        )
        total = out(run("count(//*[@type])", stdin=JSON_NESTED))
        assert out(run(q, stdin=JSON_NESTED)) == total

    def test_type_is_the_only_attribute(self):
        assert out(run("count(//a/@*)", stdin='{"a": 1}')) == "1"


# Spec: "Preserve JSON key order in converted XML."
# Context: document order of the generated children matches the textual order
# of the keys in the source JSON, not sorted order.


class TestKeyOrderPreserved:
    def test_children_follow_source_key_order(self):
        doc = '{"zeta": 1, "alpha": 2, "mid": 3}'
        assert out(run("-t", "/root/*", stdin=doc)) == "1\n2\n3"

    def test_order_is_not_alphabetical(self):
        doc = '{"zeta": 1, "alpha": 2}'
        assert out(run("name(/root/*[1])", stdin=doc)) == "zeta"

    def test_nested_object_order_is_preserved(self):
        doc = '{"o": {"z": 1, "a": 2}}'
        assert out(run("name(/root/o/*[1])", stdin=doc)) == "z"

    def test_serialized_output_shows_source_order(self):
        o = json_root('{"zeta": 1, "alpha": 2}')
        assert o.index("zeta") < o.index("alpha")

    def test_array_order_is_preserved_alongside_keys(self):
        doc = '{"a": 1, "list": [10, 20], "b": 2}'
        assert out(run("-t", "//*[@type!='list']", stdin=doc)) == "1\n10\n20\n2"


# Spec: "JSON keys that are not valid XML element names are invalid input and
# must produce stderr output with exit code `1` (include terms like
# `json`/`key`/`invalid`)."
# Context: detected during conversion, at any depth. See T22, T23.


class TestInvalidJsonKeys:
    @pytest.mark.parametrize(
        "key", ["a b", "1abc", "", "-x", ".x", "a$b", "#h", "a/b", "a\tb", "a?"]
    )
    def test_invalid_key_exits_one(self, key):
        import json as _json

        proc = run("/root", stdin=_json.dumps({key: 1}))
        assert proc.returncode == 1
        assert proc.stdout == b""

    def test_invalid_key_writes_to_stderr(self):
        assert run("/root", stdin='{"a b": 1}').stderr != b""

    def test_invalid_key_message_mentions_the_expected_terms(self):
        e = err(run("/root", stdin='{"a b": 1}')).lower()
        assert "json" in e
        assert "key" in e
        assert "invalid" in e

    def test_invalid_nested_key_also_errors(self):
        # T23: validation is recursive, not just top-level.
        proc = run("/root", stdin='{"ok": {"bad key": 1}}')
        assert proc.returncode == 1
        assert "key" in err(proc).lower()

    def test_invalid_key_inside_an_array_entry_errors(self):
        proc = run("/root", stdin='[{"bad key": 1}]')
        assert proc.returncode == 1

    def test_colon_key_is_invalid(self):
        # T22 choice: a colon makes an XML QName, not a plain element name.
        proc = run("/root", stdin='{"a:b": 1}')
        assert proc.returncode == 1
        assert "key" in err(proc).lower()

    @pytest.mark.parametrize("key", ["a", "A", "_a", "a1", "a-b", "a.b", "a_b", "x0-_."])
    def test_valid_keys_are_accepted(self, key):
        import json as _json

        proc = run("/root", stdin=_json.dumps({key: 1}))
        assert proc.returncode == 0
        assert proc.stderr == b""

    def test_error_is_not_an_xml_parse_error(self):
        e = err(run("/root", stdin='{"a b": 1}')).lower()
        assert "json" in e


# ---------------------------------------------------------------------------
# End-to-end sanity for the JSON spec
# ---------------------------------------------------------------------------


class TestJsonEndToEnd:
    def test_full_nested_document_serialization(self):
        o = json_root(JSON_NESTED)
        assert o.startswith("<root>")
        assert '<user type="dict">' in o
        assert '<id type="int">7</id>' in o
        assert '<tags type="list">' in o
        assert '<item type="str">x</item>' in o
        assert '<ok type="bool">false</ok>' in o
        assert '<note type="null"></note>' in o

    def test_top_level_array_serialization(self):
        o = json_root('[1, "two", null]')
        assert '<item type="int">1</item>' in o
        assert '<item type="str">two</item>' in o
        assert '<item type="null"></item>' in o

    def test_css_selector_over_json(self):
        assert out(run("--css", "user id::text", stdin=JSON_NESTED)) == "7"

    def test_text_all_over_json(self):
        # The converted tree has no whitespace text nodes, so descendant text
        # concatenates with nothing between the parts.
        assert out(run("--text-all", "/root/user", stdin=JSON_NESTED)) == "7xy"

    def test_attribute_query_lists_types_in_order(self):
        assert out(run("//@type", stdin='{"a": 1, "b": "s"}')) == "int\nstr"

    def test_no_match_over_json_is_silent(self):
        proc = run("//nope", stdin=JSON_OBJ)
        assert proc.returncode == 0
        assert proc.stdout == b"" and proc.stderr == b""

    def test_successful_json_run_writes_nothing_to_stderr(self):
        assert run("/root", stdin=JSON_OBJ).stderr == b""

    def test_json_pretty_print_has_single_trailing_newline(self):
        o = json_root('{"a": 1}')
        assert o.endswith("</root>\n")
        assert not o.endswith("\n\n")


# ===========================================================================
# File Input, First-Result, and Compact Output  (follow-up spec)
# ===========================================================================

# Shared helpers for the file-input spec -------------------------------------


def write(tmp_path, name, text, encoding="utf-8"):
    """Write `text` to tmp_path/name and return the path as a string."""
    path = tmp_path / name
    path.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return str(path)


# ---------------------------------------------------------------------------
# CLI Additions
# ---------------------------------------------------------------------------

# Spec: "`-f`, `--first`: return only first result."
# Context: a new option in the [OPTIONS] slot, with both a short and a long
# spelling. Its output effect is specified separately under Output Rules.


class TestFirstFlagExists:
    @pytest.mark.parametrize("flag", ["-f", "--first"])
    def test_flag_is_accepted(self, flag):
        proc = run(flag, "//a/text()", stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stderr == b""

    @pytest.mark.parametrize("flag", ["-f", "--first"])
    def test_short_and_long_spellings_agree(self, flag):
        assert out(run(flag, "//a/text()", stdin=FLAT)) == out(
            run("--first", "//a/text()", stdin=FLAT)
        )

    def test_flag_is_listed_in_help(self):
        h = out(run("--help"))
        assert "--first" in h
        assert "-f" in h

    def test_returns_only_the_first_result(self):
        assert out(run("--first", "//a/text()", stdin=FLAT)) == "one"

    def test_without_the_flag_all_results_are_returned(self):
        assert out(run("//a/text()", stdin=FLAT)) == "one\ntwo"

    def test_flag_may_follow_the_query(self):
        assert out(run("//a/text()", "--first", stdin=FLAT)) == "one"


# Spec: "`-c`, `--compact`: compact output mode."
# Context: the second new option; its meaning is pinned down under Output
# Rules ("affects XML serialization only").


class TestCompactFlagExists:
    @pytest.mark.parametrize("flag", ["-c", "--compact"])
    def test_flag_is_accepted(self, flag):
        proc = run(flag, "//a", stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stderr == b""

    def test_flag_is_listed_in_help(self):
        h = out(run("--help"))
        assert "--compact" in h
        assert "-c" in h

    @pytest.mark.parametrize("flag", ["-c", "--compact"])
    def test_short_and_long_spellings_agree(self, flag):
        assert out(run(flag, "//book[1]", stdin=CATALOG)) == out(
            run("--compact", "//book[1]", stdin=CATALOG)
        )

    def test_compact_does_not_collide_with_css(self):
        # `-c` is compact; `--css` keeps its own long-only spelling.
        assert out(run("-c", "--css", "b", stdin=FLAT)) == "<b>three</b>"

    def test_both_new_flags_combine(self):
        proc = run("-f", "-c", "//a", stdin=FLAT)
        assert proc.returncode == 0
        assert out(proc) == "<a>one</a>"

    def test_new_flags_combine_with_existing_flags(self):
        proc = run("-f", "-c", "--css", "-t", "a", stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stderr == b""


# ---------------------------------------------------------------------------
# Input Source
# ---------------------------------------------------------------------------

# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: reverses the earlier spec's "accepted but not used". See T7
# (annotation).


class TestInfilePrecedence:
    def test_file_contents_win_over_stdin(self, tmp_path):
        path = write(tmp_path, "in.xml", "<root><a>FROM_FILE</a></root>")
        assert out(run("//a/text()", path, stdin=FLAT)) == "FROM_FILE"

    def test_stdin_is_not_mixed_into_the_result(self, tmp_path):
        path = write(tmp_path, "in.xml", "<root><a>FROM_FILE</a></root>")
        o = out(run("//a/text()", path, stdin=FLAT))
        assert "one" not in o and "two" not in o

    def test_stdin_is_used_when_no_infile_is_given(self):
        assert out(run("//a/text()", stdin=FLAT)) == "one\ntwo"

    def test_file_is_used_when_stdin_is_empty(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        assert out(run("//a/text()", path, stdin="")) == "one\ntwo"

    def test_file_error_is_not_masked_by_usable_stdin(self, tmp_path):
        # Precedence is absolute: a bad path does not silently fall back.
        proc = run("//a/text()", str(tmp_path / "nope.xml"), stdin=FLAT)
        assert proc.returncode == 1
        assert proc.stdout == b""

    def test_query_and_file_only_no_stdin_stream(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = subprocess.run(
            [sys.executable, XJQ, "//b/text()", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        assert proc.stdout.decode("utf-8") == "three"

    def test_dash_is_a_plain_path_not_stdin(self, tmp_path):
        # T31: `-` is not given an alias meaning.
        proc = subprocess.run(
            [sys.executable, XJQ, "//a/text()", "--", "-"],
            input=FLAT.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 1
        assert proc.stderr != b""


# Spec: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: a third and later positional is accepted and discarded, not an
# error. Unknown *options* remain errors. See T33.


class TestExtraPositionalsIgnored:
    def test_third_positional_is_accepted(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("//a/text()", path, "extra")
        assert proc.returncode == 0
        assert out(proc) == "one\ntwo"

    def test_many_extra_positionals_are_accepted(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("//a/text()", path, "e1", "e2", "e3")
        assert proc.returncode == 0
        assert out(proc) == "one\ntwo"

    def test_extra_positionals_are_never_opened(self, tmp_path):
        path = write(tmp_path, "in.xml", "<root><a>REAL</a></root>")
        decoy = write(tmp_path, "decoy.xml", "<root><a>DECOY</a></root>")
        assert out(run("//a/text()", path, decoy)) == "REAL"

    def test_nonexistent_extra_positional_is_not_an_error(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("//a/text()", path, "/no/such/file/at/all.xml")
        assert proc.returncode == 0

    def test_extras_do_not_shift_the_infile_slot(self, tmp_path):
        # The *second* positional is still INFILE even with extras present.
        path = write(tmp_path, "in.xml", "<root><a>SECOND</a></root>")
        assert out(run("//a/text()", path, "x", "y")) == "SECOND"

    def test_unknown_option_is_still_rejected(self, tmp_path):
        # T33: leniency covers positionals only.
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("//a/text()", path, "--not-an-option")
        assert proc.returncode != 0

    def test_extras_work_with_flags(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("--first", "//a/text()", path, "extra")
        assert proc.returncode == 0
        assert out(proc) == "one"


# Spec: "Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed."
# Context: file bytes become characters via UTF-8 specifically, and a leading
# byte-order mark must not reach the parser. See T30, T32.


class TestInfileDecoding:
    def test_utf8_content_round_trips(self, tmp_path):
        path = write(tmp_path, "in.xml", "<root><a>café</a></root>")
        assert out(run("//a/text()", path)) == "café"

    def test_non_ascii_beyond_the_bmp(self, tmp_path):
        path = write(tmp_path, "in.xml", "<root><a>\U0001f600</a></root>")
        assert out(run("//a/text()", path)) == "\U0001f600"

    def test_bom_before_xml_declaration_is_allowed(self, tmp_path):
        text = '﻿<?xml version="1.0" encoding="UTF-8"?><root><a>x</a></root>'
        path = write(tmp_path, "in.xml", text)
        proc = run("//a/text()", path)
        assert proc.returncode == 0
        assert out(proc) == "x"

    def test_bom_before_bare_root_element_is_allowed(self, tmp_path):
        path = write(tmp_path, "in.xml", "﻿<root><a>x</a></root>")
        proc = run("//a/text()", path)
        assert proc.returncode == 0
        assert out(proc) == "x"

    def test_bom_before_json_is_allowed(self, tmp_path):
        path = write(tmp_path, "in.json", '﻿{"a": 1}')
        proc = run("//a/text()", path)
        assert proc.returncode == 0
        assert out(proc) == "1"

    def test_bom_does_not_leak_into_output(self, tmp_path):
        path = write(tmp_path, "in.xml", "﻿<root><a>x</a></root>")
        assert "﻿" not in out(run("/root", path))

    def test_utf8_declared_encoding_is_consistent(self, tmp_path):
        text = '<?xml version="1.0" encoding="UTF-8"?><root><a>café</a></root>'
        path = write(tmp_path, "in.xml", text)
        assert out(run("//a/text()", path)) == "café"

    def test_non_utf8_bytes_are_a_read_error(self, tmp_path):
        # T30: the file could not be decoded as the spec requires.
        path = tmp_path / "in.xml"
        path.write_bytes(b"<root><a>caf\xe9</a></root>")
        proc = run("//a/text()", str(path))
        assert proc.returncode == 1
        assert proc.stderr != b""
        assert proc.stdout == b""


# Spec: "Apply JSON auto-detection to file input: treat as JSON object/array
# when detected, otherwise parse as XML/HTML."
# Context: the earlier spec's stdin auto-detection now runs on file bytes too,
# with the same JSON-to-XML conversion contract.


class TestJsonDetectionOnFileInput:
    def test_json_object_file_is_detected(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_OBJ)
        assert out(run("//name/text()", path)) == "Ada"

    def test_json_array_file_is_detected(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_ARR)
        assert out(run("//item/text()", path)) == "1\n2\n3"

    def test_json_file_gets_the_root_wrapper(self, tmp_path):
        path = write(tmp_path, "in.json", '{"a": 1}')
        o = out(run("/root", path))
        assert o.startswith("<root>")

    def test_json_file_gets_type_attributes(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_NESTED)
        o = out(run("/root", path))
        assert '<id type="int">7</id>' in o

    def test_xml_file_is_still_parsed_as_xml(self, tmp_path):
        path = write(tmp_path, "in.xml", CATALOG)
        assert out(run("//book[1]/title/text()", path)) == "XPath Basics"

    def test_non_json_file_falls_back_to_xml(self, tmp_path):
        path = write(tmp_path, "in.xml", '{"a": 1,}')
        proc = run("/root", path)
        assert proc.returncode == 1

    def test_top_level_primitive_file_falls_back_to_xml(self, tmp_path):
        path = write(tmp_path, "in.json", "42")
        proc = run("/root", path)
        assert proc.returncode == 1

    def test_file_extension_does_not_drive_detection(self, tmp_path):
        # Detection inspects content, not the name.
        path = write(tmp_path, "in.xml", JSON_OBJ)
        assert out(run("//name/text()", path)) == "Ada"

    def test_css_works_over_a_json_file(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_NESTED)
        assert out(run("--css", "user id::text", path)) == "7"

    def test_file_json_matches_stdin_json(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_NESTED)
        assert out(run("/root", path)) == out(run("/root", stdin=JSON_NESTED))


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: the new error mode introduced by opening INFILE. See T34, T35.


class TestFileErrors:
    def test_missing_file_exits_one(self, tmp_path):
        proc = run("//a", str(tmp_path / "nope.xml"))
        assert proc.returncode == 1

    def test_missing_file_writes_to_stderr(self, tmp_path):
        proc = run("//a", str(tmp_path / "nope.xml"))
        assert proc.stderr != b""

    def test_missing_file_writes_nothing_to_stdout(self, tmp_path):
        proc = run("//a", str(tmp_path / "nope.xml"))
        assert proc.stdout == b""

    def test_message_names_the_path(self, tmp_path):
        missing = str(tmp_path / "nope.xml")
        assert "nope.xml" in err(run("//a", missing))

    def test_unreadable_file_exits_one(self, tmp_path):
        blocked = tmp_path / "blocked.xml"
        blocked.write_text("<root/>")
        blocked.chmod(0o000)
        try:
            proc = run("//a", str(blocked))
            if os.geteuid() != 0:
                assert proc.returncode == 1
                assert proc.stderr != b""
        finally:
            blocked.chmod(0o644)

    def test_directory_as_infile_exits_one(self, tmp_path):
        # T34: any OSError from the path is the same failure.
        proc = run("//a", str(tmp_path))
        assert proc.returncode == 1
        assert proc.stderr != b""

    def test_file_error_precedes_query_evaluation(self, tmp_path):
        # An invalid query plus a missing file still exits 1 with a message.
        proc = run("//[", str(tmp_path / "nope.xml"))
        assert proc.returncode == 1
        assert proc.stderr != b""

    def test_empty_file_is_an_empty_document_error(self, tmp_path):
        # T35: reading succeeded, so this is the earlier spec's empty-input
        # error rather than the file error. Both exit 1.
        path = write(tmp_path, "empty.xml", "")
        proc = run("//a", path)
        assert proc.returncode == 1
        assert proc.stderr != b""

    def test_malformed_xml_file_exits_one(self, tmp_path):
        path = write(tmp_path, "bad.xml", "<root><a></root>")
        proc = run("//a", path)
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# Output Rules
# ---------------------------------------------------------------------------

# Spec: "`--first` applies across text, attribute, and XML-node results."
# Context: the same truncation for all three result kinds. See T26, T27.


class TestFirstAcrossResultKinds:
    def test_first_text_result(self):
        assert out(run("--first", "//a/text()", stdin=FLAT)) == "one"

    def test_first_attribute_result(self):
        assert out(run("--first", "//book/@id", stdin=CATALOG)) == "b1"

    def test_first_attribute_result_is_document_order_first(self):
        assert out(run("--first", "//@currency", stdin=CATALOG)) == "USD"

    def test_first_text_result_of_many(self):
        assert out(run("--first", "//title/text()", stdin=CATALOG)) == "XPath Basics"

    def test_first_xml_node_result(self):
        o = out(run("--first", "//book", stdin=CATALOG))
        assert "XPath Basics" in o
        assert "XPath Avance" not in o

    def test_xml_node_output_is_still_first_only_without_the_flag(self):
        # T27: the earlier "output only the first node" rule is unrevoked, so
        # --first is observably a no-op for a pure node-set.
        assert out(run("//book", stdin=CATALOG)) == out(
            run("--first", "//book", stdin=CATALOG)
        )

    def test_first_still_emits_a_single_line_for_text(self):
        assert "\n" not in out(run("--first", "//a/text()", stdin=FLAT))

    def test_first_with_text_flag(self):
        assert out(run("--first", "--text", "//book", stdin=CATALOG)) == ""

    def test_first_with_text_all_flag(self):
        o = out(run("--first", "--text-all", "//title", stdin=CATALOG))
        assert o == "XPath Basics"

    def test_first_with_css_text_pseudo_element(self):
        assert out(run("--first", "--css", "a::text", stdin=FLAT)) == "one"

    def test_first_with_css_node_output(self):
        assert out(run("--first", "--compact", "--css", "a", stdin=FLAT)) == "<a>one</a>"

    def test_first_over_json_input(self):
        assert out(run("--first", "//@type", stdin='{"a": 1, "b": "s"}')) == "int"

    def test_first_with_a_single_result_is_unchanged(self):
        assert out(run("--first", "//b/text()", stdin=FLAT)) == out(
            run("//b/text()", stdin=FLAT)
        )

    def test_first_with_a_scalar_result_is_unchanged(self):
        assert out(run("--first", "count(//a)", stdin=FLAT)) == "2"

    def test_first_with_string_function_result(self):
        assert out(run("--first", "string(//a)", stdin=FLAT)) == "one"

    def test_first_of_a_mixed_union_takes_the_document_order_first_item(self):
        # T26: truncation happens on the raw result list, before the
        # node-vs-text branch is chosen, so a leading text node wins.
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("--first", "//a/text() | //b", stdin=doc)) == "1"

    # Retired and reversed by the json/union spec: a mixed union is now
    # written as text results, so without --first both members print as text.
    # The T26 truncation this class is about is unchanged. See T42.
    def test_mixed_union_without_first_prints_every_member_as_text(self):
        doc = "<r><a>1</a><b>2</b></r>"
        assert out(run("//a/text() | //b", stdin=doc)) == "1\n2"

    def test_first_applies_to_file_input_too(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        assert out(run("--first", "//a/text()", path)) == "one"

    def test_first_does_not_change_the_exit_code(self):
        assert run("--first", "//a/text()", stdin=FLAT).returncode == 0


# Spec: "`--first` with no matches remains silent (no output)."
# Context: truncating an empty result set is still an empty result set; the
# earlier no-match rule (silent, exit 0) is unchanged.


class TestFirstWithNoMatches:
    @pytest.mark.parametrize(
        "query", ["//nope", "//nope/text()", "//a/@missing", "//a[99]"]
    )
    def test_no_match_with_first_is_silent(self, query):
        proc = run("--first", query, stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stdout == b""
        assert proc.stderr == b""

    def test_no_match_with_first_writes_not_even_a_newline(self):
        assert run("--first", "//nope", stdin=FLAT).stdout == b""

    def test_no_match_with_first_and_compact_is_silent(self):
        proc = run("--first", "--compact", "//nope", stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stdout == b""

    def test_no_match_with_first_and_text_is_silent(self):
        proc = run("--first", "--text", "//nope", stdin=FLAT)
        assert proc.returncode == 0
        assert proc.stdout == b""

    def test_no_match_with_first_over_json_is_silent(self):
        proc = run("--first", "//nope", stdin=JSON_OBJ)
        assert proc.returncode == 0
        assert proc.stdout == b"" and proc.stderr == b""

    def test_no_match_with_first_from_a_file(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        proc = run("--first", "//nope", path)
        assert proc.returncode == 0
        assert proc.stdout == b""


# Spec: "`--compact` affects XML serialization only: compact XML output has no
# added pretty-print formatting."
# Context: the flag changes how element results are serialized and nothing
# else. See T28 (what "added" excludes) and T29 (trailing newline).


class TestCompactXmlSerialization:
    def test_no_indentation_is_added(self):
        doc = "<r><outer><inner>v</inner></outer></r>"
        assert out(run("--compact", "//outer", stdin=doc)) == (
            "<outer><inner>v</inner></outer>"
        )

    def test_pretty_mode_does_add_indentation(self):
        doc = "<r><outer><inner>v</inner></outer></r>"
        o = out(run("//outer", stdin=doc))
        assert o != "<outer><inner>v</inner></outer>"
        assert "\n" in o

    def test_compact_output_has_no_trailing_newline(self):
        # T29.
        doc = "<r><outer><inner>v</inner></outer></r>"
        assert not out(run("--compact", "//outer", stdin=doc)).endswith("\n")

    def test_compact_preserves_source_whitespace(self):
        # T28 choice: only *added* formatting is withheld; the document's own
        # whitespace text nodes are character data and survive.
        o = out(run("--compact", "//book[1]", stdin=CATALOG))
        assert "<title>XPath Basics</title>" in o
        assert "\n    <title>" in o

    def test_compact_leaf_element(self):
        assert out(run("--compact", "//b", stdin=FLAT)) == "<b>three</b>"

    def test_compact_keeps_attributes(self):
        o = out(run("--compact", "//book[2]", stdin=CATALOG))
        assert 'id="b2"' in o and 'lang="fr"' in o

    def test_compact_keeps_escaping(self):
        doc = "<r><a>a &amp; b</a></r>"
        assert out(run("--compact", "//a", stdin=doc)) == "<a>a &amp; b</a>"

    def test_compact_keeps_namespace_declarations(self):
        doc = '<r xmlns:n="http://example.com/n"><n:item>x</n:item></r>'
        o = out(run("--compact", "//*[local-name()='item']", stdin=doc))
        assert "http://example.com/n" in o

    def test_compact_does_not_include_the_tail(self):
        doc = "<r><a>1</a>TAIL</r>"
        assert out(run("--compact", "//a", stdin=doc)) == "<a>1</a>"

    def test_compact_of_the_root_element(self):
        doc = "<r><a>1</a></r>"
        assert out(run("--compact", "/r", stdin=doc)) == "<r><a>1</a></r>"

    def test_compact_empty_element(self):
        doc = "<r><e/></r>"
        o = out(run("--compact", "//e", stdin=doc))
        assert o in ("<e/>", "<e></e>")

    # "affects XML serialization only"
    def test_compact_does_not_change_text_results(self):
        assert out(run("--compact", "//a/text()", stdin=FLAT)) == out(
            run("//a/text()", stdin=FLAT)
        )

    def test_compact_does_not_change_attribute_results(self):
        assert out(run("--compact", "//book/@id", stdin=CATALOG)) == "b1\nb2"

    def test_compact_does_not_change_text_flag_output(self):
        assert out(run("--compact", "--text", "//title", stdin=CATALOG)) == out(
            run("--text", "//title", stdin=CATALOG)
        )

    def test_compact_does_not_change_css_text_output(self):
        assert out(run("--compact", "--css", "a::text", stdin=FLAT)) == "one\ntwo"

    def test_compact_does_not_change_scalar_results(self):
        assert out(run("--compact", "count(//a)", stdin=FLAT)) == "2"

    def test_compact_does_not_change_the_no_match_rule(self):
        proc = run("--compact", "//nope", stdin=FLAT)
        assert proc.returncode == 0 and proc.stdout == b""

    def test_compact_still_outputs_only_the_first_node(self):
        assert out(run("--compact", "//a", stdin=FLAT)) == "<a>one</a>"

    def test_compact_applies_to_file_input(self, tmp_path):
        path = write(tmp_path, "in.xml", "<r><outer><inner>v</inner></outer></r>")
        assert out(run("--compact", "//outer", path)) == "<outer><inner>v</inner></outer>"


# Spec: "For JSON-derived input, `--compact` still applies to resulting XML
# output."
# Context: the converted tree is serialized by the same code path, so the flag
# is not bypassed by the JSON branch.


class TestCompactOverJsonInput:
    def test_compact_json_object_is_one_line(self):
        assert out(run("--compact", "/root", stdin='{"a": 1}')) == (
            '<root><a type="int">1</a></root>'
        )

    def test_pretty_json_object_is_indented(self):
        o = out(run("/root", stdin='{"a": 1}'))
        assert "\n" in o
        assert o != '<root><a type="int">1</a></root>'

    def test_compact_json_array_is_one_line(self):
        assert out(run("--compact", "/root", stdin="[1, 2]")) == (
            '<root><item type="int">1</item><item type="int">2</item></root>'
        )

    def test_compact_json_nested(self):
        o = out(run("--compact", "//user", stdin=JSON_NESTED))
        assert o == (
            '<user type="dict"><id type="int">7</id>'
            '<tags type="list"><item type="str">x</item>'
            '<item type="str">y</item></tags></user>'
        )

    def test_compact_json_has_no_trailing_newline(self):
        assert not out(run("--compact", "/root", stdin='{"a": 1}')).endswith("\n")

    def test_compact_json_keeps_empty_elements_open(self):
        # The earlier spec's "no self-closing tags" contract is unaffected.
        o = out(run("--compact", "/root", stdin='{"note": null}'))
        assert o == '<root><note type="null"></note></root>'

    def test_compact_json_from_a_file(self, tmp_path):
        path = write(tmp_path, "in.json", '{"a": 1}')
        assert out(run("--compact", "/root", path)) == (
            '<root><a type="int">1</a></root>'
        )

    def test_compact_json_with_first(self):
        assert out(run("-c", "-f", "//item", stdin="[1, 2]")) == (
            '<item type="int">1</item>'
        )

    def test_compact_does_not_change_json_text_results(self):
        assert out(run("--compact", "//@type", stdin='{"a": 1, "b": "s"}')) == "int\nstr"


# ---------------------------------------------------------------------------
# End-to-end sanity for the file-input spec
# ---------------------------------------------------------------------------


class TestFileSpecEndToEnd:
    def test_file_plus_first_plus_compact(self, tmp_path):
        path = write(tmp_path, "catalog.xml", CATALOG)
        o = out(run("-f", "-c", "//title", path))
        assert o == "<title>XPath Basics</title>"

    def test_file_plus_css_plus_first_text(self, tmp_path):
        path = write(tmp_path, "catalog.xml", CATALOG)
        assert out(run("-f", "--css", "book title::text", path)) == "XPath Basics"

    def test_json_file_plus_first_attribute(self, tmp_path):
        path = write(tmp_path, "in.json", JSON_NESTED)
        assert out(run("-f", "//@type", path)) == "dict"

    def test_successful_file_run_writes_nothing_to_stderr(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        assert run("//a/text()", path).stderr == b""

    def test_exit_code_zero_for_file_input(self, tmp_path):
        path = write(tmp_path, "in.xml", FLAT)
        assert run("//a/text()", path).returncode == 0

    def test_all_new_flags_with_extras_and_a_file(self, tmp_path):
        path = write(tmp_path, "in.xml", CATALOG)
        proc = run("--first", "--compact", "//book", path, "ignored", "also-ignored")
        assert proc.returncode == 0
        assert proc.stdout.decode("utf-8").startswith("<book")


# ===========================================================================
# Smart Output Formatting, JSON Export, and Multi-XPath
# ===========================================================================

# Fixtures for this spec ----------------------------------------------------

# Leaf elements with clean text, plus a container whose immediate text is only
# indentation. Used throughout the JSON-export and union sections.
SHOP = """<shop>
  <item id="i1">
    <name>Widget</name>
    <price>10</price>
  </item>
  <item id="i2">
    <name>Gadget</name>
    <price>20</price>
  </item>
</shop>
"""

# Mixed content: immediate text is split around a child element.
MIXEDC = "<r><p>Hello <b>bold</b> world</p></r>"

# Namespaced document, for the tag_name question (T49) and CSS `a|b`.
NSDOC = '<root xmlns:k="urn:k"><k:title>Kay</k:title><title>Plain</title></root>'


def jload(proc):
    """Parse the tool's stdout as JSON; fails loudly if it is not JSON."""
    return json.loads(proc.stdout.decode("utf-8"))


# ---------------------------------------------------------------------------
# CLI Addition
# ---------------------------------------------------------------------------

# Spec: "- `-j`, `--json`: JSON export mode for XML element results."
# Context: a new flag with both a short and a long spelling, joining the
# existing option set. It is a mode switch, not an argument-taking option.


class TestJsonFlagExists:
    def test_long_flag_is_accepted(self):
        assert run("--json", "//name", stdin=SHOP).returncode == 0

    def test_short_flag_is_accepted(self):
        assert run("-j", "//name", stdin=SHOP).returncode == 0

    def test_short_and_long_flag_agree(self):
        assert out(run("-j", "//name", stdin=SHOP)) == out(
            run("--json", "//name", stdin=SHOP)
        )

    def test_flag_takes_no_value(self):
        # `--json //name` must not swallow the query as the flag's argument.
        proc = run("--json", "//name", stdin=SHOP)
        assert proc.returncode == 0
        assert "Widget" in out(proc)

    def test_flag_is_listed_in_help(self):
        h = out(run("--help"))
        assert "--json" in h
        assert "-j" in h

    def test_flag_may_follow_the_query(self):
        assert run("//name", "--json", stdin=SHOP).returncode == 0

    def test_json_mode_applies_to_xml_element_results(self):
        # "JSON export mode for XML element results": elements are the input
        # to the export.
        assert jload(run("-j", "//name", stdin=SHOP)) == [
            {"name": "Widget"},
            {"name": "Gadget"},
        ]

    def test_without_the_flag_nothing_changes(self):
        assert out(run("//name", stdin=SHOP)).startswith("<name>")


# ---------------------------------------------------------------------------
# Output Precedence
# ---------------------------------------------------------------------------

# Spec: "When multiple output flags are present: 1. `--text-all` 2. `--text`
#        3. `--json` 4. default auto-format behavior"
# Context: an ordered list. The first flag present in this order decides the
# output mode and the lower-ranked ones are inert.


class TestOutputPrecedence:
    def test_text_all_beats_text(self):
        # Pre-existing rule, restated by the ranking.
        assert out(run("--text-all", "--text", "//p", stdin=MIXEDC)) == "Hello bold world"

    def test_text_all_beats_json(self):
        o = out(run("--text-all", "--json", "//name", stdin=SHOP))
        assert o == "Widget\nGadget"

    def test_text_beats_json(self):
        o = out(run("--text", "--json", "//name", stdin=SHOP))
        assert o == "Widget\nGadget"

    def test_text_all_beats_text_and_json_together(self):
        o = out(run("--text-all", "--text", "--json", "//p", stdin=MIXEDC))
        assert o == "Hello bold world"

    def test_json_beats_default_auto_format(self):
        o = out(run("--json", "//name", stdin=SHOP))
        assert o.lstrip().startswith("[")
        assert "<name>" not in o

    def test_default_auto_format_is_last(self):
        # With no output flag at all, the earlier node rule still applies.
        assert out(run("//name", stdin=SHOP)) == "<name>Widget</name>\n"

    def test_flag_order_on_the_command_line_does_not_matter(self):
        a = out(run("--json", "--text", "//name", stdin=SHOP))
        b = out(run("--text", "--json", "//name", stdin=SHOP))
        assert a == b == "Widget\nGadget"

    def test_text_all_with_json_is_not_json(self):
        with pytest.raises(ValueError):
            json.loads(out(run("--text-all", "--json", "//name", stdin=SHOP)))


# Spec: "`--json` has no effect when results are already auto-detected as text
#        (e.g. text()/attribute outputs)."
# Context: the auto-format step classifies a result set as text or as XML
# nodes; --json only reaches the node side. See T48.


class TestJsonNoEffectOnTextResults:
    def test_no_effect_on_a_text_node_query(self):
        assert out(run("--json", "//name/text()", stdin=SHOP)) == "Widget\nGadget"

    def test_no_effect_on_an_attribute_query(self):
        assert out(run("--json", "//item/@id", stdin=SHOP)) == "i1\ni2"

    def test_no_effect_on_a_string_function_result(self):
        assert out(run("--json", "string(//name)", stdin=SHOP)) == "Widget"

    def test_no_effect_on_a_number_result(self):
        assert out(run("--json", "count(//item)", stdin=SHOP)) == "2"

    def test_no_effect_on_a_boolean_result(self):
        assert out(run("--json", "//item/@id = 'i1'", stdin=SHOP)) == "true"

    def test_text_result_output_is_identical_with_and_without_json(self):
        assert out(run("--json", "//name/text()", stdin=SHOP)) == out(
            run("//name/text()", stdin=SHOP)
        )

    def test_no_effect_is_not_an_error(self):
        proc = run("--json", "//name/text()", stdin=SHOP)
        assert proc.returncode == 0
        assert proc.stderr == b""

    def test_mixed_union_counts_as_text_so_json_is_inert(self):
        # T48: a mixed result set is written as text results, so --json
        # cannot reach it.
        o = out(run("--json", "//name/text() | //price", stdin=SHOP))
        assert o == "Widget\n10\nGadget\n20"


# Spec: "In `--css` mode, `--json` has no effect and output follows the normal
#        CSS rules for the query."
# Context: --css and --json are compatible on the command line, but --json is
# inert there.


class TestJsonInertInCssMode:
    def test_css_node_output_is_unchanged_by_json(self):
        assert out(run("--css", "--json", "name", stdin=SHOP)) == (
            "<name>Widget</name>\n"
        )

    def test_css_json_matches_css_without_json(self):
        assert out(run("--css", "--json", "name", stdin=SHOP)) == out(
            run("--css", "name", stdin=SHOP)
        )

    def test_css_text_pseudo_element_is_unchanged_by_json(self):
        assert out(run("--css", "--json", "name::text", stdin=SHOP)) == "Widget\nGadget"

    def test_css_with_json_and_first(self):
        assert out(run("--css", "--json", "--first", "name", stdin=SHOP)) == (
            "<name>Widget</name>\n"
        )

    def test_css_with_json_and_compact(self):
        assert out(run("--css", "--json", "--compact", "name", stdin=SHOP)) == (
            "<name>Widget</name>"
        )

    def test_css_with_json_exits_zero(self):
        proc = run("--css", "--json", "name", stdin=SHOP)
        assert proc.returncode == 0
        assert proc.stderr == b""

    def test_css_json_output_is_not_json(self):
        with pytest.raises(ValueError):
            json.loads(out(run("--css", "--json", "name", stdin=SHOP)))


# ---------------------------------------------------------------------------
# JSON Export Contract
# ---------------------------------------------------------------------------

# Spec: "Export shape: JSON array of objects `{tag_name: immediate_text_content}`."
# Context: the top level is an array; each matched element becomes one object
# with exactly one key, the tag name, mapped to the element's immediate text.


class TestJsonExportShape:
    def test_top_level_is_an_array(self):
        assert isinstance(jload(run("-j", "//name", stdin=SHOP)), list)

    def test_one_object_per_matched_element(self):
        assert len(jload(run("-j", "//name", stdin=SHOP))) == 2

    def test_each_entry_is_an_object(self):
        assert all(isinstance(e, dict) for e in jload(run("-j", "//item", stdin=SHOP)))

    def test_each_object_has_exactly_one_key(self):
        assert all(len(e) == 1 for e in jload(run("-j", "//name", stdin=SHOP)))

    def test_the_key_is_the_tag_name(self):
        assert list(jload(run("-j", "//name", stdin=SHOP))[0]) == ["name"]

    def test_the_value_is_the_text_content(self):
        assert jload(run("-j", "//price", stdin=SHOP)) == [
            {"price": "10"},
            {"price": "20"},
        ]

    def test_values_are_strings_not_numbers(self):
        # Element text is text; no numeric coercion is specified.
        assert jload(run("-j", "//price", stdin=SHOP))[0]["price"] == "10"

    def test_document_order_is_preserved(self):
        assert [list(e.values())[0] for e in jload(run("-j", "//name", stdin=SHOP))] == [
            "Widget",
            "Gadget",
        ]

    def test_all_matches_are_exported_not_just_the_first(self):
        # T41: the default node rule ("first node only") does not apply here.
        assert len(jload(run("-j", "//*", stdin=SHOP))) == 7

    def test_different_tag_names_in_one_export(self):
        assert jload(run("-j", "//item/*", stdin=SHOP)) == [
            {"name": "Widget"},
            {"price": "10"},
            {"name": "Gadget"},
            {"price": "20"},
        ]

    def test_export_is_valid_json(self):
        json.loads(out(run("-j", "//item", stdin=SHOP)))

    def test_namespaced_tag_name_is_the_verbatim_tag(self):
        # T49: Clark notation, namespace retained.
        assert jload(run("-j", "//*[local-name()='title']", stdin=NSDOC)) == [
            {"{urn:k}title": "Kay"},
            {"title": "Plain"},
        ]

    def test_root_element_exports_as_one_object(self):
        assert jload(run("-j", "/shop", stdin=SHOP)) == [{"shop": ""}]


# Spec: "Use immediate text only (exclude descendant text from child elements)."
# Context: the exported value is the element's own text, not its subtree's.
# See T39.


class TestImmediateTextOnly:
    def test_child_element_text_is_excluded(self):
        # <item> has no text of its own, only indentation.
        assert jload(run("-j", "//item", stdin=SHOP)) == [{"item": ""}, {"item": ""}]

    def test_leaf_text_is_included(self):
        assert jload(run("-j", "//name", stdin=SHOP))[0] == {"name": "Widget"}

    def test_mixed_content_keeps_the_parents_own_text(self):
        # T39: element.text plus each child's tail, normalized -> "Hello world";
        # the child <b>'s own text "bold" is excluded.
        assert jload(run("-j", "//p", stdin=MIXEDC)) == [{"p": "Hello world"}]

    def test_indentation_only_text_normalizes_to_empty(self):
        assert jload(run("-j", "/shop", stdin=SHOP)) == [{"shop": ""}]

    def test_internal_whitespace_is_collapsed(self):
        doc = "<r><a>one   two\n  three</a></r>"
        assert jload(run("-j", "//a", stdin=doc)) == [{"a": "one two three"}]

    def test_surrounding_whitespace_is_stripped(self):
        doc = "<r><a>  padded  </a></r>"
        assert jload(run("-j", "//a", stdin=doc)) == [{"a": "padded"}]

    def test_empty_element_exports_empty_string(self):
        assert jload(run("-j", "//a", stdin="<r><a></a></r>")) == [{"a": ""}]

    def test_deep_descendant_text_is_not_pulled_up(self):
        doc = "<r><a><b><c>deep</c></b></a></r>"
        assert jload(run("-j", "//a", stdin=doc)) == [{"a": ""}]


# Spec: "Default JSON formatting: 2-space indent."
# Context: without --compact the array is pretty-printed with an indent of two
# spaces per level.


class TestJsonDefaultIndent:
    def test_output_is_multiline(self):
        assert "\n" in out(run("-j", "//name", stdin=SHOP))

    def test_exact_two_space_indent_layout(self):
        assert out(run("-j", "//name", stdin=SHOP)) == (
            '[\n'
            '  {\n'
            '    "name": "Widget"\n'
            '  },\n'
            '  {\n'
            '    "name": "Gadget"\n'
            '  }\n'
            ']'
        )

    def test_matches_json_dumps_indent_two(self):
        assert out(run("-j", "//name", stdin=SHOP)) == json.dumps(
            [{"name": "Widget"}, {"name": "Gadget"}], indent=2
        )

    def test_object_lines_are_indented_by_two(self):
        lines = out(run("-j", "//name", stdin=SHOP)).split("\n")
        assert lines[1] == "  {"

    def test_key_lines_are_indented_by_four(self):
        lines = out(run("-j", "//name", stdin=SHOP)).split("\n")
        assert lines[2] == '    "name": "Widget"'

    def test_no_trailing_newline(self):
        # T37.
        assert not out(run("-j", "//name", stdin=SHOP)).endswith("\n")


# Spec: "With `--compact`, produce zero-indent JSON layout (no leading whitespace)."
# Context: --compact previously only affected XML serialization; it now also
# selects the zero-indent JSON layout. See T36.


class TestJsonCompactLayout:
    def test_no_line_has_leading_whitespace(self):
        o = out(run("-j", "-c", "//name", stdin=SHOP))
        assert all(line == line.lstrip() for line in o.split("\n"))

    def test_exact_zero_indent_layout(self):
        assert out(run("-j", "-c", "//name", stdin=SHOP)) == (
            '[\n'
            '{\n'
            '"name": "Widget"\n'
            '},\n'
            '{\n'
            '"name": "Gadget"\n'
            '}\n'
            ']'
        )

    def test_matches_json_dumps_indent_zero(self):
        assert out(run("-j", "--compact", "//name", stdin=SHOP)) == json.dumps(
            [{"name": "Widget"}, {"name": "Gadget"}], indent=0
        )

    def test_compact_is_still_valid_json(self):
        assert jload(run("-j", "-c", "//name", stdin=SHOP)) == [
            {"name": "Widget"},
            {"name": "Gadget"},
        ]

    def test_compact_has_no_trailing_newline(self):
        assert not out(run("-j", "-c", "//name", stdin=SHOP)).endswith("\n")

    def test_compact_differs_from_default(self):
        assert out(run("-j", "-c", "//name", stdin=SHOP)) != out(
            run("-j", "//name", stdin=SHOP)
        )

    def test_compact_long_form_flag(self):
        assert out(run("--json", "--compact", "//name", stdin=SHOP)) == out(
            run("-j", "-c", "//name", stdin=SHOP)
        )

    def test_compact_still_affects_xml_when_json_is_absent(self):
        assert out(run("-c", "//name", stdin=SHOP)) == "<name>Widget</name>"


# Spec: "With `--first`, still return a JSON array containing one exported element."
# Context: --first narrows the export to one element but does not unwrap the
# array. See T41.


class TestJsonWithFirst:
    def test_result_is_still_an_array(self):
        assert isinstance(jload(run("-j", "-f", "//name", stdin=SHOP)), list)

    def test_array_has_exactly_one_entry(self):
        assert len(jload(run("-j", "-f", "//name", stdin=SHOP))) == 1

    def test_the_entry_is_the_first_match(self):
        assert jload(run("-j", "-f", "//name", stdin=SHOP)) == [{"name": "Widget"}]

    def test_not_unwrapped_to_a_bare_object(self):
        assert out(run("-j", "-f", "//name", stdin=SHOP)).lstrip()[0] == "["

    def test_exact_default_layout_with_first(self):
        assert out(run("-j", "--first", "//name", stdin=SHOP)) == (
            '[\n  {\n    "name": "Widget"\n  }\n]'
        )

    def test_exact_compact_layout_with_first(self):
        assert out(run("-j", "-f", "-c", "//name", stdin=SHOP)) == (
            '[\n{\n"name": "Widget"\n}\n]'
        )

    def test_first_with_a_single_match_is_the_same(self):
        assert out(run("-j", "-f", "/shop", stdin=SHOP)) == out(
            run("-j", "/shop", stdin=SHOP)
        )

    def test_first_still_wins_over_json_for_text_results(self):
        assert out(run("-j", "-f", "//name/text()", stdin=SHOP)) == "Widget"


# Spec: interaction of JSON export with an empty result set.
# Context: not stated by the spec; the tool's standing rule is that no match
# prints nothing. See T40.


class TestJsonWithNoMatches:
    def test_no_match_prints_nothing(self):
        assert out(run("-j", "//nope", stdin=SHOP)) == ""

    def test_no_match_exits_zero(self):
        assert run("-j", "//nope", stdin=SHOP).returncode == 0

    def test_no_match_writes_nothing_to_stderr(self):
        assert run("-j", "//nope", stdin=SHOP).stderr == b""


# Spec: JSON export over JSON input (the auto-detected JSON->XML tree).
# Context: the converted tree is a normal document (T25), so --json exports
# from it like any other element result.


class TestJsonExportOverJsonInput:
    def test_export_converted_elements(self):
        assert jload(run("-j", "//a", stdin='{"a": 1}')) == [{"a": "1"}]

    def test_export_converted_array_items(self):
        assert jload(run("-j", "//item", stdin="[1, 2]")) == [
            {"item": "1"},
            {"item": "2"},
        ]

    def test_export_container_has_empty_immediate_text(self):
        assert jload(run("-j", "/root", stdin='{"a": 1}')) == [{"root": ""}]


# ---------------------------------------------------------------------------
# XPath Union
# ---------------------------------------------------------------------------

# Spec: "Support XPath `|` union in XPath mode."
# Context: `|` in an XPath QUERY combines node-sets; results come back in
# document order.


class TestXPathUnionSupported:
    def test_union_is_accepted(self):
        assert run("//name | //price", stdin=SHOP).returncode == 0

    def test_union_matches_both_sub_paths(self):
        assert out(run("--text", "//name | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_union_results_are_in_document_order(self):
        assert out(run("--text", "//price | //name", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_union_deduplicates_overlapping_sub_paths(self):
        assert out(run("--text", "//name | //name", stdin=SHOP)) == "Widget\nGadget"

    def test_union_of_three_sub_paths(self):
        assert out(run("--text", "//name | //price | //item/@id", stdin=SHOP)) == (
            "i1\nWidget\n10\ni2\nGadget\n20"
        )

    def test_union_without_flags_uses_default_node_output(self):
        assert out(run("//name | //price", stdin=SHOP)) == "<name>Widget</name>\n"

    def test_union_with_json_exports_every_match(self):
        assert jload(run("-j", "//name | //price", stdin=SHOP)) == [
            {"name": "Widget"},
            {"price": "10"},
            {"name": "Gadget"},
            {"price": "20"},
        ]

    def test_union_with_first(self):
        assert out(run("-f", "//name | //price", stdin=SHOP)) == (
            "<name>Widget</name>\n"
        )

    def test_a_pipe_inside_a_string_literal_is_not_a_union(self):
        # T43: only top-level pipes split the query.
        doc = "<r><a x='p|q'>hit</a><a x='z'>miss</a></r>"
        assert out(run("--text", "//a[@x='p|q']", stdin=doc)) == "hit"

    def test_union_over_json_input(self):
        assert out(run("--text", "//a | //b", stdin='{"a": 1, "b": 2}')) == "1\n2"


# Spec: "`--text` and `--text-all` apply across union queries."
# Context: the text flags are not disabled by a union; they extract from every
# matched node of every sub-path.


class TestTextFlagsAcrossUnions:
    def test_text_covers_both_sub_paths(self):
        assert out(run("-t", "//name | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_text_keeps_one_line_per_element(self):
        # T46: only --text-all concatenates.
        assert out(run("-t", "//name | //price", stdin=SHOP)).count("\n") == 3

    def test_text_over_a_union_of_containers(self):
        assert out(run("-t", "//item | //name", stdin=SHOP)) == (
            "\nWidget\n\nGadget"
        )

    def test_text_all_covers_both_sub_paths(self):
        o = out(run("--text-all", "//name | //price", stdin=SHOP))
        for word in ("Widget", "10", "Gadget", "20"):
            assert word in o

    def test_text_flags_work_with_a_union_including_attributes(self):
        assert out(run("-t", "//item/@id | //name", stdin=SHOP)) == (
            "i1\nWidget\ni2\nGadget"
        )


# Spec: "For XPath union queries with active `--text-all`, concatenate
#        descendant text across all union matches into one normalized output
#        string."
# Context: this replaces the one-line-per-element shape with a single line.
# See T43 (union detection) and T44 (space-joined).


class TestUnionTextAllConcatenation:
    def test_output_is_a_single_line(self):
        assert "\n" not in out(run("--text-all", "//name | //price", stdin=SHOP))

    def test_exact_concatenated_string(self):
        assert out(run("--text-all", "//name | //price", stdin=SHOP)) == (
            "Widget 10 Gadget 20"
        )

    def test_descendant_text_is_used_not_immediate_text(self):
        assert out(run("--text-all", "//item | //shop/nothing", stdin=SHOP)) == (
            "Widget 10 Gadget 20"
        )

    def test_result_is_normalized(self):
        doc = "<r><a>  one\n  two  </a><b>three</b></r>"
        assert out(run("--text-all", "//a | //b", stdin=doc)) == "one two three"

    def test_non_union_text_all_still_prints_one_line_per_element(self):
        # T43: the concatenation is specific to union queries.
        assert out(run("--text-all", "//name", stdin=SHOP)) == "Widget\nGadget"

    def test_union_with_a_single_match_is_just_that_text(self):
        assert out(run("--text-all", "//shop/none | (//name)[1]", stdin=SHOP)) == (
            "Widget"
        )

    def test_union_matching_nothing_prints_nothing(self):
        assert out(run("--text-all", "//x | //y", stdin=SHOP)) == ""

    def test_three_way_union_concatenates_all(self):
        assert out(run("--text-all", "//name | //price | //item/@id", stdin=SHOP)) == (
            "i1 Widget 10 i2 Gadget 20"
        )

    def test_text_does_not_concatenate(self):
        # T46.
        assert "\n" in out(run("--text", "//name | //price", stdin=SHOP))

    def test_pipe_inside_a_predicate_does_not_trigger_concatenation(self):
        # T43: not a top-level union, so the per-element shape stands.
        doc = "<r><a x='p|q'>one</a><a x='p|q'>two</a></r>"
        assert out(run("--text-all", "//a[@x='p|q']", stdin=doc)) == "one\ntwo"


# Spec: "If `--first` is also active with union + `--text-all`, only the first
#        matched union node contributes to the output."
# Context: the concatenation still happens, but over a one-node sequence.


class TestUnionTextAllWithFirst:
    def test_only_the_first_node_contributes(self):
        assert out(run("--text-all", "-f", "//name | //price", stdin=SHOP)) == "Widget"

    def test_first_means_first_in_document_order_not_first_sub_path(self):
        assert out(run("--text-all", "-f", "//price | //name", stdin=SHOP)) == "Widget"

    def test_first_node_descendant_text_is_still_used(self):
        assert out(run("--text-all", "-f", "//item | //price", stdin=SHOP)) == (
            "Widget 10"
        )

    def test_output_is_a_single_line(self):
        assert "\n" not in out(run("--text-all", "--first", "//name | //price", stdin=SHOP))

    def test_long_flag_spelling(self):
        assert out(run("--text-all", "--first", "//name | //price", stdin=SHOP)) == (
            "Widget"
        )

    def test_first_with_a_union_that_matches_nothing(self):
        assert out(run("--text-all", "-f", "//x | //y", stdin=SHOP)) == ""


# Spec: "If any union sub-path already performs text extraction, text flags are
#        treated as no-op query modifiers."
# Context: e.g. `//a/text() | //b`. The flags then change nothing, including
# the union concatenation. See T45.


class TestUnionSubPathAlreadyExtractsText:
    def test_text_all_is_a_no_op_so_no_concatenation(self):
        # Without the no-op rule this would be one concatenated line.
        assert out(run("--text-all", "//name/text() | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_text_is_a_no_op(self):
        assert out(run("--text", "//name/text() | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_no_op_output_equals_the_unflagged_output(self):
        assert out(run("--text-all", "//name/text() | //price", stdin=SHOP)) == out(
            run("//name/text() | //price", stdin=SHOP)
        )

    def test_it_is_enough_that_one_sub_path_extracts(self):
        assert out(run("--text-all", "//price | //name/text()", stdin=SHOP)) == out(
            run("//price | //name/text()", stdin=SHOP)
        )

    def test_all_sub_paths_extracting_text(self):
        assert out(run("--text-all", "//name/text() | //price/text()", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_a_text_predicate_is_not_text_extraction(self):
        # T45: `text()` inside a predicate filters, it does not extract.
        doc = "<r><a>one</a><b>two</b></r>"
        assert out(run("--text-all", "//a[contains(text(),'one')] | //b", stdin=doc)) == (
            "one two"
        )

    def test_trailing_predicate_after_text_still_counts_as_extraction(self):
        assert out(run("--text-all", "//name/text()[1] | //price", stdin=SHOP)) == out(
            run("//name/text()[1] | //price", stdin=SHOP)
        )

    def test_no_op_does_not_disable_first(self):
        assert out(run("--text-all", "-f", "//name/text() | //price", stdin=SHOP)) == (
            "Widget"
        )

    def test_attribute_sub_path_is_not_text_extraction(self):
        # T45: attributes are not `text()`, so the flags stay live.
        assert out(run("--text-all", "//item/@id | //name", stdin=SHOP)) == (
            "i1 Widget i2 Gadget"
        )


# Spec: "A union with mixed result types is written as text results."
# Context: `//a/text() | //b` yields strings and elements in one list; the
# whole thing is rendered through the text branch rather than as XML. See T42.


class TestMixedUnionIsTextResults:
    def test_mixed_union_is_not_serialized_as_xml(self):
        o = out(run("//name/text() | //price", stdin=SHOP))
        assert "<price>" not in o

    def test_mixed_union_text_lines(self):
        assert out(run("//name/text() | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_element_members_contribute_descendant_text(self):
        # T42: string-value, so a container yields its whole subtree's text.
        assert out(run("//name/text() | //item", stdin=SHOP)) == (
            "Widget 10\nWidget\nGadget 20\nGadget"
        )

    def test_attribute_and_element_mix_is_text(self):
        assert out(run("//item/@id | //name", stdin=SHOP)) == (
            "i1\nWidget\ni2\nGadget"
        )

    def test_uniform_element_union_is_still_xml(self):
        assert out(run("//name | //price", stdin=SHOP)) == "<name>Widget</name>\n"

    def test_uniform_text_union_is_text(self):
        assert out(run("//name/text() | //price/text()", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )

    def test_mixed_union_results_are_normalized(self):
        doc = "<r><a>one</a><b>  two   three </b></r>"
        assert out(run("//a/text() | //b", stdin=doc)) == "one\ntwo three"

    def test_mixed_union_with_first_keeps_the_first_item(self):
        # T26: --first truncates before rendering.
        assert out(run("-f", "//name/text() | //price", stdin=SHOP)) == "Widget"

    def test_mixed_union_with_first_landing_on_an_element(self):
        assert out(run("-f", "//price/text() | //name", stdin=SHOP)) == (
            "<name>Widget</name>\n"
        )

    def test_mixed_union_with_compact_is_unaffected(self):
        assert out(run("-c", "//name/text() | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )


# Spec: "In CSS mode, pass `|` through as CSS query text (no XPath union
#        semantics). If the CSS engine rejects the selector, report a CSS
#        selector error on stderr with exit code `1`."
# Context: in CSS, `|` is the namespace separator, not a union operator.
# See T47.


class TestPipeInCssMode:
    def test_spaced_pipe_is_a_css_error_exit_1(self):
        proc = run("--css", "name | price", stdin=SHOP)
        assert proc.returncode == 1

    def test_spaced_pipe_error_goes_to_stderr(self):
        proc = run("--css", "name | price", stdin=SHOP)
        assert proc.stderr != b""
        assert proc.stdout == b""

    def test_spaced_pipe_error_mentions_css_selector(self):
        e = err(run("--css", "name | price", stdin=SHOP)).lower()
        assert "css" in e and "selector" in e

    def test_pipe_is_not_treated_as_a_union(self):
        # If it were a union it would succeed and print <name>Widget</name>.
        assert run("--css", "name | price", stdin=SHOP).returncode == 1

    def test_unspaced_pipe_is_a_namespace_selector_not_a_union(self):
        # `k|title` selects <title> in the namespace bound to prefix `k`;
        # the tool binds no prefixes, so the engine rejects it. T47.
        proc = run("--css", "k|title", stdin=NSDOC)
        assert proc.returncode == 1
        assert "css" in err(proc).lower()

    def test_unspaced_pipe_never_unions(self):
        # `name|price` must not produce the union's output.
        proc = run("--css", "name|price", stdin=SHOP)
        assert proc.stdout == b""
        assert proc.returncode == 1

    def test_universal_namespace_pipe_selects_any_namespace(self):
        # `*|title` is well-formed CSS the engine can translate.
        proc = run("--css", "*|title", stdin=NSDOC)
        assert proc.returncode == 0

    def test_pipe_error_is_unaffected_by_text_flags(self):
        assert run("--css", "--text", "name | price", stdin=SHOP).returncode == 1

    def test_pipe_error_is_unaffected_by_json(self):
        assert run("--css", "--json", "name | price", stdin=SHOP).returncode == 1

    def test_xpath_mode_pipe_still_unions(self):
        # The CSS rule is scoped to --css.
        assert out(run("--text", "//name | //price", stdin=SHOP)) == (
            "Widget\n10\nGadget\n20"
        )


# ---------------------------------------------------------------------------
# End-to-end sanity for the json/union spec
# ---------------------------------------------------------------------------


class TestJsonUnionEndToEnd:
    def test_json_union_first_compact_together(self):
        assert out(run("-j", "-c", "-f", "//name | //price", stdin=SHOP)) == (
            '[\n{\n"name": "Widget"\n}\n]'
        )

    def test_json_from_a_file(self, tmp_path):
        path = write(tmp_path, "shop.xml", SHOP)
        assert jload(run("-j", "//name", path)) == [
            {"name": "Widget"},
            {"name": "Gadget"},
        ]

    def test_union_from_a_file(self, tmp_path):
        path = write(tmp_path, "shop.xml", SHOP)
        assert out(run("--text-all", "//name | //price", path)) == "Widget 10 Gadget 20"

    def test_successful_json_run_writes_nothing_to_stderr(self):
        assert run("-j", "//name", stdin=SHOP).stderr == b""

    def test_json_run_exits_zero(self):
        assert run("-j", "//name", stdin=SHOP).returncode == 0

    def test_union_run_exits_zero(self):
        assert run("//name | //price", stdin=SHOP).returncode == 0

    def test_invalid_xpath_union_still_errors(self):
        proc = run("//name | ///", stdin=SHOP)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_json_with_extra_positionals_and_a_file(self, tmp_path):
        path = write(tmp_path, "shop.xml", SHOP)
        proc = run("--json", "//name", path, "ignored")
        assert proc.returncode == 0
        assert jload(proc) == [{"name": "Widget"}, {"name": "Gadget"}]
