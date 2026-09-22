"""Test suite for xjq.py, derived phrase-by-phrase from the spec.

Each section carries a comment quoting the spec phrase it covers, plus the
context needed to read it. Interpretation choices are cross-referenced to
AMBIGUITIES.md entries (T1..T7).
"""

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

    def test_query_plus_infile_is_accepted(self):
        proc = run("//a/text()", "some_file.xml", stdin=FLAT)
        assert proc.returncode == 0

    def test_third_positional_is_rejected(self):
        proc = run("//a/text()", "f1.xml", "f2.xml", stdin=FLAT)
        assert proc.returncode != 0

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
# Context: parsed and discarded; it is never opened. See T7.


class TestInfileIgnored:
    def test_nonexistent_infile_is_not_an_error(self):
        proc = run("//a/text()", "/no/such/path/at/all.xml", stdin=FLAT)
        assert proc.returncode == 0
        assert out(proc) == "one\ntwo"

    def test_infile_contents_are_never_read(self, tmp_path):
        decoy = tmp_path / "decoy.xml"
        decoy.write_text("<root><a>FROM_FILE</a></root>")
        proc = run("//a/text()", str(decoy), stdin=FLAT)
        assert proc.returncode == 0
        assert out(proc) == "one\ntwo"
        assert "FROM_FILE" not in out(proc)

    def test_unreadable_infile_is_not_an_error(self, tmp_path):
        blocked = tmp_path / "blocked.xml"
        blocked.write_text("<root/>")
        blocked.chmod(0o000)
        try:
            proc = run("//a/text()", str(blocked), stdin=FLAT)
            assert proc.returncode == 0
            assert out(proc) == "one\ntwo"
        finally:
            blocked.chmod(0o644)

    def test_infile_that_is_a_directory_is_not_an_error(self, tmp_path):
        proc = run("//a/text()", str(tmp_path), stdin=FLAT)
        assert proc.returncode == 0


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

    # T4: a mixed node/string union routes to the XML branch.
    def test_union_of_node_and_text_outputs_first_node(self):
        doc = "<r><a>1</a><b>2</b></r>"
        o = out(run("//a | //b/text()", stdin=doc))
        assert "<a>1</a>" in o


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

    def test_css_still_accepts_the_infile_positional(self):
        proc = run("--css", "p", "ignored.xml", stdin=TWOP)
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
