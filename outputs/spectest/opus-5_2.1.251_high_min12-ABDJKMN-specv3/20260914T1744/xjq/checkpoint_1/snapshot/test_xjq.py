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
        "{\"json\": true}",
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
