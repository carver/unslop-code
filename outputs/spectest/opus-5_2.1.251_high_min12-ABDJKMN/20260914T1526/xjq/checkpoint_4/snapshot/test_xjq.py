"""Tests for xjq.py, derived phrase-by-phrase from the spec.

Each test section is headed by a comment quoting the spec phrase it covers.
Ambiguous phrases are cross-referenced to AMBIGUITIES.md (T1..T11).
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "xjq.py")


def run(query, stdin="", *extra_args):
    """Invoke the CLI exactly as the spec spells it: python xjq.py [OPTIONS] QUERY [INFILE]."""
    argv = [sys.executable, SCRIPT, query, *extra_args]
    data = stdin.encode() if isinstance(stdin, str) else stdin
    return subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def out(proc):
    return proc.stdout.decode()


def err(proc):
    return proc.stderr.decode()


SIMPLE = "<root><item id='1'>alpha</item><item id='2'>beta</item></root>"


# ---------------------------------------------------------------------------
# Spec: "Implement executable `xjq.py`" / "`python xjq.py [OPTIONS] QUERY [INFILE]`"
# Context: CLI. The script must exist and be runnable as `python xjq.py ...`.
# ---------------------------------------------------------------------------
class TestExecutable:
    def test_script_file_exists(self):
        assert os.path.isfile(SCRIPT)

    def test_runs_as_python_script(self):
        proc = run("//item/text()", SIMPLE)
        assert proc.returncode == 0

    def test_has_shebang(self):
        with open(SCRIPT, "rb") as fh:
            assert fh.readline().startswith(b"#!")

    # Context: [OPTIONS] is never named in the spec -- see AMBIGUITIES T1.
    def test_help_option_available(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--help"],
            input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        assert b"QUERY" in proc.stdout or b"query" in proc.stdout


# ---------------------------------------------------------------------------
# Spec: "`QUERY`: XPath expression."
# Context: CLI. First positional argument is the XPath to evaluate.
# ---------------------------------------------------------------------------
class TestQueryArgument:
    def test_query_is_first_positional(self):
        proc = run("//item[@id='2']/text()", SIMPLE)
        assert proc.returncode == 0
        assert out(proc) == "beta\n"

    def test_absolute_path_query(self):
        proc = run("/root/item[1]/text()", SIMPLE)
        assert out(proc) == "alpha\n"

    def test_query_is_required(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT],
            input=SIMPLE.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Spec: "`INFILE`: accepted positional argument but not used."
# SUPERSEDED by "`INFILE` takes precedence over stdin when both are present."
# Context: CLI. The second positional is still accepted; it is now the input
# source rather than a no-op. Full coverage lives in TestInfilePrecedence.
# ---------------------------------------------------------------------------
class TestInfileAccepted:
    def test_infile_accepted(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<other><item>USED</item></other>")
        proc = run("//item/text()", SIMPLE, str(path))
        assert proc.returncode == 0

    def test_infile_contents_are_now_used(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<other><item>USED</item></other>")
        proc = run("//item/text()", SIMPLE, str(path))
        assert out(proc) == "USED\n"


# ---------------------------------------------------------------------------
# Spec: "Input source: stdin."
# Context: Behavior. The document always comes from standard input.
# ---------------------------------------------------------------------------
class TestStdinIsInput:
    def test_reads_document_from_stdin(self):
        proc = run("//a/text()", "<a>from-stdin</a>")
        assert out(proc) == "from-stdin\n"

    def test_reads_bytes_with_encoding_declaration(self):
        doc = b"<?xml version='1.0' encoding='utf-8'?><a>caf\xc3\xa9</a>"
        proc = run("//a/text()", doc)
        assert proc.returncode == 0
        assert out(proc) == "café\n"


# ---------------------------------------------------------------------------
# Spec: "Parse stdin as XML/HTML using case-sensitive element matching."
# Context: Behavior. Element names differing only in case are distinct.
# See AMBIGUITIES T2 for the XML-vs-HTML parsing decision.
# ---------------------------------------------------------------------------
class TestCaseSensitiveParsing:
    DOC = "<Root><Item>upper</Item><item>lower</item></Root>"

    def test_uppercase_name_matches_only_uppercase(self):
        proc = run("//Item/text()", self.DOC)
        assert out(proc) == "upper\n"

    def test_lowercase_name_matches_only_lowercase(self):
        proc = run("//item/text()", self.DOC)
        assert out(proc) == "lower\n"

    def test_wrong_case_root_does_not_match(self):
        proc = run("/root/Item/text()", self.DOC)
        assert proc.returncode == 0
        assert out(proc) == ""

    def test_mixed_case_attribute_names_are_distinct(self):
        doc = "<r><e Id='A' id='b'/></r>"
        proc = run("//e/@Id", doc)
        assert out(proc) == "A\n"

    def test_html_shaped_document_parses(self):
        doc = "<html><body><p>Hello</p></body></html>"
        proc = run("//p/text()", doc)
        assert proc.returncode == 0
        assert out(proc) == "Hello\n"


# ---------------------------------------------------------------------------
# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: Behavior. XPath 1.0 axes, predicates and core functions work.
# ---------------------------------------------------------------------------
class TestXPath10:
    def test_predicate_by_position(self):
        proc = run("//item[2]/text()", SIMPLE)
        assert out(proc) == "beta\n"

    def test_attribute_selection(self):
        proc = run("//item/@id", SIMPLE)
        assert out(proc) == "1\n2\n"

    def test_core_function_string(self):
        proc = run("string(//item[1])", SIMPLE)
        assert out(proc) == "alpha\n"

    def test_core_function_concat(self):
        proc = run("concat(//item[1]/text(), '-', //item[2]/text())", SIMPLE)
        assert out(proc) == "alpha-beta\n"

    def test_axis_query(self):
        doc = "<r><a><b>deep</b></a></r>"
        proc = run("//b/ancestor::a/b/text()", doc)
        assert out(proc) == "deep\n"

    def test_union_of_text_nodes(self):
        doc = "<r><a>one</a><b>two</b></r>"
        proc = run("//a/text() | //b/text()", doc)
        assert out(proc) == "one\ntwo\n"

    # Context: XPath 1.0 has no XPath 2.0+ constructs; those are invalid here.
    def test_xpath2_only_construct_is_an_error(self):
        proc = run("//item/text() => upper-case()", SIMPLE)
        assert proc.returncode == 1

    # Context: number/boolean results -- see AMBIGUITIES T4.
    def test_count_function_result(self):
        proc = run("count(//item)", SIMPLE)
        assert proc.returncode == 0
        assert out(proc).strip() == "2"

    def test_boolean_result(self):
        proc = run("//item[1]/text() = 'alpha'", SIMPLE)
        assert proc.returncode == 0
        assert out(proc).strip().lower() in {"true", "1"}


# ---------------------------------------------------------------------------
# Spec: "Exit code `0` on successful execution, including zero matches."
# Context: Behavior.
# ---------------------------------------------------------------------------
class TestExitZero:
    def test_exit_zero_on_match(self):
        assert run("//item/text()", SIMPLE).returncode == 0

    def test_exit_zero_on_zero_matches(self):
        assert run("//nothing", SIMPLE).returncode == 0

    def test_exit_zero_on_zero_matching_attributes(self):
        assert run("//item/@missing", SIMPLE).returncode == 0

    def test_exit_zero_on_empty_string_function_result(self):
        assert run("string(//nothing)", SIMPLE).returncode == 0


# ---------------------------------------------------------------------------
# Spec: "Text/attribute results: strip each result, collapse internal
#        whitespace runs to single spaces, then join results with each on a
#        newline."
# Context: Output.
# ---------------------------------------------------------------------------
class TestTextOutput:
    def test_single_text_result(self):
        proc = run("//a/text()", "<a>hello</a>")
        assert out(proc) == "hello\n"

    def test_each_result_on_its_own_line(self):
        proc = run("//item/text()", SIMPLE)
        assert out(proc) == "alpha\nbeta\n"

    def test_leading_and_trailing_whitespace_stripped(self):
        proc = run("//a/text()", "<a>   padded   </a>")
        assert out(proc) == "padded\n"

    def test_internal_whitespace_runs_collapsed(self):
        proc = run("//a/text()", "<a>one     two</a>")
        assert out(proc) == "one two\n"

    def test_newlines_and_tabs_collapse_to_single_space(self):
        proc = run("//a/text()", "<a>one \n\t  two\n\nthree</a>")
        assert out(proc) == "one two three\n"

    def test_attribute_values_are_stripped_and_collapsed(self):
        proc = run("//a/@t", "<a t='  x   y  '/>")
        assert out(proc) == "x y\n"

    def test_multiple_attributes_joined_by_newline(self):
        proc = run("//item/@id", SIMPLE)
        assert out(proc) == "1\n2\n"

    def test_string_function_result_is_collapsed(self):
        proc = run("string(//a)", "<a>  a\n  b  </a>")
        assert out(proc) == "a b\n"

    def test_text_output_goes_to_stdout_not_stderr(self):
        proc = run("//a/text()", "<a>hi</a>")
        assert err(proc) == ""

    # Context: whitespace-only text node -- see AMBIGUITIES T5.
    def test_whitespace_only_result_becomes_empty_line(self):
        proc = run("//a/text()", "<a>   </a>")
        assert proc.returncode == 0
        assert out(proc) == "\n"


# ---------------------------------------------------------------------------
# Spec: "XML node results: pretty-print serialized XML"
# Context: Output. See AMBIGUITIES T6 for serialization details.
# ---------------------------------------------------------------------------
class TestXmlNodeOutput:
    def test_element_result_is_serialized_as_xml(self):
        proc = run("//item[1]", SIMPLE)
        assert proc.returncode == 0
        assert out(proc).strip() == '<item id="1">alpha</item>'

    def test_nested_element_is_indented(self):
        doc = "<root><a><b>x</b></a></root>"
        proc = run("//a", doc)
        text = out(proc)
        lines = text.rstrip("\n").split("\n")
        assert lines[0] == "<a>"
        assert lines[1].startswith(" ") and lines[1].strip() == "<b>x</b>"
        assert lines[-1] == "</a>"

    def test_root_element_result(self):
        proc = run("/root", "<root><a>x</a></root>")
        text = out(proc)
        assert text.startswith("<root>")
        assert "<a>x</a>" in text
        assert text.rstrip("\n").endswith("</root>")

    def test_attributes_preserved_in_serialization(self):
        proc = run("//item[@id='2']", SIMPLE)
        assert 'id="2"' in out(proc)

    def test_self_closing_element(self):
        proc = run("//e", "<r><e a='1'/></r>")
        assert out(proc).strip() == '<e a="1"/>'

    def test_tail_text_not_included(self):
        proc = run("//a", "<r><a>x</a>TAIL</r>")
        assert "TAIL" not in out(proc)

    def test_no_xml_declaration(self):
        proc = run("//item[1]", "<?xml version='1.0'?>" + SIMPLE)
        assert "<?xml" not in out(proc)

    def test_xml_output_goes_to_stdout_not_stderr(self):
        proc = run("//item[1]", SIMPLE)
        assert err(proc) == ""

    def test_output_ends_with_single_newline(self):
        proc = run("//item[1]", SIMPLE)
        text = out(proc)
        assert text.endswith("\n") and not text.endswith("\n\n")


# ---------------------------------------------------------------------------
# Spec: "when multiple XML nodes match, output only the first node"
# Context: Output.
# ---------------------------------------------------------------------------
class TestFirstNodeOnly:
    def test_only_first_of_two_elements(self):
        proc = run("//item", SIMPLE)
        text = out(proc)
        assert "alpha" in text
        assert "beta" not in text

    def test_first_means_document_order(self):
        doc = "<r><x n='1'/><x n='2'/><x n='3'/></r>"
        proc = run("//x", doc)
        assert out(proc).strip() == '<x n="1"/>'

    def test_wildcard_match_outputs_only_first(self):
        proc = run("//*", SIMPLE)
        text = out(proc)
        assert text.lstrip().startswith("<root>")
        assert text.count("<root>") == 1

    def test_exit_code_zero_with_multiple_nodes(self):
        assert run("//item", SIMPLE).returncode == 0


# ---------------------------------------------------------------------------
# Spec: "No-match output: write nothing to stdout/stderr."
# Context: Output.
# ---------------------------------------------------------------------------
class TestNoMatch:
    def test_no_matching_element_writes_nothing(self):
        proc = run("//missing", SIMPLE)
        assert out(proc) == ""
        assert err(proc) == ""
        assert proc.returncode == 0

    def test_no_matching_text_writes_nothing(self):
        proc = run("//missing/text()", SIMPLE)
        assert out(proc) == ""
        assert err(proc) == ""

    def test_no_matching_attribute_writes_nothing(self):
        proc = run("//item/@nope", SIMPLE)
        assert out(proc) == ""
        assert err(proc) == ""

    def test_failing_predicate_writes_nothing(self):
        proc = run("//item[@id='99']", SIMPLE)
        assert out(proc) == ""
        assert err(proc) == ""


# ---------------------------------------------------------------------------
# Spec: "Invalid XPath: stderr message, exit code `1`; message should
#        reference `xpath`."
# Context: Errors.
# ---------------------------------------------------------------------------
class TestInvalidXPath:
    BAD = ["//[", "///", "//a[", "count(", "//a/@", "foo:bar(", "//a bad b"]

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_xpath_exits_one(self, query):
        proc = run(query, SIMPLE)
        assert proc.returncode == 1

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_xpath_message_on_stderr(self, query):
        proc = run(query, SIMPLE)
        assert err(proc).strip() != ""

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_xpath_message_mentions_xpath(self, query):
        proc = run(query, SIMPLE)
        assert "xpath" in err(proc).lower()

    def test_invalid_xpath_writes_nothing_to_stdout(self):
        proc = run("//[", SIMPLE)
        assert out(proc) == ""

    def test_unknown_function_is_invalid_xpath(self):
        proc = run("no-such-function(//a)", SIMPLE)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    # Context: unbound namespace prefix -- see AMBIGUITIES T11.
    def test_unbound_namespace_prefix_is_invalid_xpath(self):
        proc = run("//ns:item", SIMPLE)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()


# ---------------------------------------------------------------------------
# Spec: "Malformed/empty XML input: stderr message, exit code `1`; message
#        should reference `xml`/`parse`."
# Context: Errors. See AMBIGUITIES T2 and T7.
# ---------------------------------------------------------------------------
class TestMalformedInput:
    MALFORMED = [
        "<a><b></a>",
        "<unclosed>",
        "not xml at all",
        "<a>&bad;</a>",
        "<a><</a>",
        "<a>x</a><b>y</b>",
    ]

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_exits_one(self, doc):
        proc = run("//a", doc)
        assert proc.returncode == 1

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_message_mentions_xml_or_parse(self, doc):
        proc = run("//a", doc)
        low = err(proc).lower()
        assert "xml" in low or "parse" in low

    @pytest.mark.parametrize("doc", MALFORMED)
    def test_malformed_writes_nothing_to_stdout(self, doc):
        proc = run("//a", doc)
        assert out(proc) == ""

    def test_empty_input_exits_one(self):
        proc = run("//a", "")
        assert proc.returncode == 1
        low = err(proc).lower()
        assert "xml" in low or "parse" in low

    def test_whitespace_only_input_exits_one(self):
        proc = run("//a", "   \n\t  ")
        assert proc.returncode == 1
        low = err(proc).lower()
        assert "xml" in low or "parse" in low

    def test_error_message_is_single_line_ish(self):
        proc = run("//a", "<a>")
        assert err(proc).strip() != ""


# ===========================================================================
# CSS Selectors and Text Extraction
# ===========================================================================

def run_argv(argv, stdin=""):
    """Invoke the CLI with an explicit argument vector (flags before QUERY)."""
    data = stdin.encode() if isinstance(stdin, str) else stdin
    return subprocess.run(
        [sys.executable, SCRIPT, *argv],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


PAGE = (
    "<html><body>"
    "<h1 class='t'>Title</h1>"
    "<div id='main'><p>One</p><p>Two</p></div>"
    "<h2 class='t'>Sub</h2>"
    "</body></html>"
)

# An element carrying text both before and after a child element.
MIXED = "<r><div>A<p>B</p>C</div></r>"


# ---------------------------------------------------------------------------
# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: CLI Additions. The flag switches the query language.
# ---------------------------------------------------------------------------
class TestCssFlag:
    def test_css_flag_accepted(self):
        proc = run_argv(["--css", "p"], PAGE)
        assert proc.returncode == 0

    def test_css_type_selector_matches(self):
        proc = run_argv(["--css", "p"], PAGE)
        assert "One" in out(proc)

    def test_css_id_selector(self):
        proc = run_argv(["--css", "#main"], PAGE)
        assert proc.returncode == 0
        assert 'id="main"' in out(proc)

    def test_css_class_selector(self):
        proc = run_argv(["--css", ".t"], PAGE)
        assert "Title" in out(proc)

    def test_css_descendant_combinator(self):
        proc = run_argv(["--css", "#main p"], PAGE)
        assert "One" in out(proc)

    def test_css_child_combinator(self):
        proc = run_argv(["--css", "body > h1"], PAGE)
        assert "Title" in out(proc)

    def test_css_attribute_selector(self):
        proc = run_argv(["--css", "[id='main']"], PAGE)
        assert 'id="main"' in out(proc)

    # Context: without --css the same query is still an XPath expression.
    def test_query_is_xpath_without_css_flag(self):
        proc = run_argv(["#main"], PAGE)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    # Context: INFILE now takes precedence over stdin, in CSS mode too.
    def test_css_query_reads_infile_positional(self, tmp_path):
        path = tmp_path / "other.html"
        path.write_text("<div><p>FromFile</p></div>")
        proc = run_argv(["--css", "p", str(path)], PAGE)
        assert proc.returncode == 0
        assert "FromFile" in out(proc)

    def test_css_no_match_writes_nothing(self):
        proc = run_argv(["--css", "article"], PAGE)
        assert proc.returncode == 0
        assert out(proc) == ""
        assert err(proc) == ""

    # Context: case-sensitive element matching -- see AMBIGUITIES T18.
    def test_css_element_names_are_case_sensitive(self):
        doc = "<Root><Item>upper</Item><item>lower</item></Root>"
        proc = run_argv(["--css", "-t", "Item"], doc)
        assert out(proc) == "upper\n"


# ---------------------------------------------------------------------------
# Spec: "`-t`, `--text`: direct text extraction from matched elements."
# Context: CLI Additions. See AMBIGUITIES T12 (works in XPath mode too)
# and T13 (what "direct text" means).
# ---------------------------------------------------------------------------
class TestTextFlag:
    def test_short_form_extracts_text(self):
        proc = run_argv(["-t", "//p"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_long_form_extracts_text(self):
        proc = run_argv(["--text", "//p"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_text_flag_with_css_query(self):
        proc = run_argv(["--css", "--text", "p"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_text_flag_replaces_xml_node_output(self):
        proc = run_argv(["-t", "//p"], PAGE)
        assert "<p>" not in out(proc)

    def test_direct_text_excludes_child_element_text(self):
        proc = run_argv(["-t", "//div"], MIXED)
        assert "B" not in out(proc)

    def test_direct_text_from_all_matched_elements(self):
        proc = run_argv(["--css", "-t", ".t"], PAGE)
        assert out(proc) == "Title\nSub\n"

    def test_text_flag_exit_zero(self):
        assert run_argv(["-t", "//p"], PAGE).returncode == 0

    def test_text_flag_no_match_writes_nothing(self):
        proc = run_argv(["-t", "//article"], PAGE)
        assert out(proc) == ""
        assert err(proc) == ""
        assert proc.returncode == 0

    # Context: element with no direct text of its own -- see AMBIGUITIES T14.
    def test_element_without_direct_text_yields_no_line(self):
        proc = run_argv(["-t", "//div"], "<r><div><p>B</p></div></r>")
        assert out(proc) == ""

    # Context: attribute results have no element to extract from -- T22.
    def test_text_flag_is_noop_for_attribute_results(self):
        proc = run_argv(["-t", "//div/@id"], PAGE)
        assert out(proc) == "main\n"


# ---------------------------------------------------------------------------
# Spec: "`--text-all`: descendant text extraction from matched elements."
# Context: CLI Additions.
# ---------------------------------------------------------------------------
class TestTextAllFlag:
    def test_text_all_collects_descendant_text(self):
        proc = run_argv(["--text-all", "//div"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_text_all_with_css_query(self):
        proc = run_argv(["--css", "--text-all", "#main"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_text_all_includes_own_and_nested_text(self):
        # See AMBIGUITIES T21: immediate text children are descendants too.
        proc = run_argv(["--text-all", "//div"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_text_all_one_text_node_per_line(self):
        proc = run_argv(["--text-all", "//div"], MIXED)
        assert len(out(proc).rstrip("\n").split("\n")) == 3

    def test_text_all_exit_zero(self):
        assert run_argv(["--text-all", "//div"], PAGE).returncode == 0

    def test_text_all_no_match_writes_nothing(self):
        proc = run_argv(["--text-all", "//article"], PAGE)
        assert out(proc) == ""
        assert err(proc) == ""

    def test_text_all_produces_no_xml_markup(self):
        proc = run_argv(["--text-all", "//body"], PAGE)
        assert "<" not in out(proc)


# ---------------------------------------------------------------------------
# Spec: "Define custom `::text` pseudo-element: `selector::text` returns
#        direct text"
# Context: CSS Query Mode. See AMBIGUITIES T13.
# ---------------------------------------------------------------------------
class TestCssTextPseudoDirect:
    def test_direct_text_of_single_element(self):
        proc = run_argv(["--css", "h1::text"], PAGE)
        assert out(proc) == "Title\n"

    def test_direct_text_of_each_matched_element(self):
        proc = run_argv(["--css", "p::text"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_direct_text_excludes_descendant_text(self):
        proc = run_argv(["--css", "div::text"], MIXED)
        assert "B" not in out(proc)

    def test_direct_text_concatenates_own_text_nodes(self):
        proc = run_argv(["--css", "div::text"], MIXED)
        assert out(proc) == "AC\n"

    def test_direct_text_with_class_selector(self):
        proc = run_argv(["--css", ".t::text"], PAGE)
        assert out(proc) == "Title\nSub\n"

    def test_direct_text_exit_zero(self):
        assert run_argv(["--css", "p::text"], PAGE).returncode == 0

    def test_direct_text_no_match_writes_nothing(self):
        proc = run_argv(["--css", "article::text"], PAGE)
        assert out(proc) == ""
        assert err(proc) == ""

    def test_direct_text_emits_no_markup(self):
        proc = run_argv(["--css", "#main::text"], PAGE)
        assert "<" not in out(proc)


# ---------------------------------------------------------------------------
# Spec: "`selector ::text` returns all descendant text nodes (one text node
#        per line)"
# Context: CSS Query Mode. The space before `::text` selects descendant mode.
# ---------------------------------------------------------------------------
class TestCssTextPseudoDescendant:
    def test_descendant_text_of_container(self):
        proc = run_argv(["--css", "#main ::text"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_descendant_text_includes_nested_and_own(self):
        proc = run_argv(["--css", "div ::text"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_one_text_node_per_line(self):
        doc = "<r><div><p>one</p><p>two</p><span>three</span></div></r>"
        proc = run_argv(["--css", "div ::text"], doc)
        assert out(proc) == "one\ntwo\nthree\n"

    def test_text_nodes_in_document_order(self):
        proc = run_argv(["--css", "body ::text"], PAGE)
        assert out(proc) == "Title\nOne\nTwo\nSub\n"

    def test_space_changes_mode_from_direct(self):
        direct = run_argv(["--css", "div::text"], MIXED)
        descendant = run_argv(["--css", "div ::text"], MIXED)
        assert out(direct) != out(descendant)

    def test_descendant_text_exit_zero(self):
        assert run_argv(["--css", "body ::text"], PAGE).returncode == 0

    def test_descendant_text_no_match_writes_nothing(self):
        proc = run_argv(["--css", "article ::text"], PAGE)
        assert out(proc) == ""
        assert err(proc) == ""

    # Context: pretty-printed input is full of whitespace-only text nodes.
    # See AMBIGUITIES T14.
    def test_whitespace_only_text_nodes_are_dropped(self):
        doc = "<div>\n  <p>a</p>\n  <p>b</p>\n</div>"
        proc = run_argv(["--css", "div ::text"], doc)
        assert out(proc) == "a\nb\n"


# ---------------------------------------------------------------------------
# Spec: "Comma-separated selectors are supported for `::text` queries when all
#        selectors use the same `::text` mode."
# Context: CSS Query Mode.
# ---------------------------------------------------------------------------
class TestCommaSeparatedTextSelectors:
    def test_two_direct_text_selectors(self):
        proc = run_argv(["--css", "h1::text, h2::text"], PAGE)
        assert proc.returncode == 0
        assert out(proc) == "Title\nSub\n"

    def test_two_descendant_text_selectors(self):
        proc = run_argv(["--css", "h1 ::text, h2 ::text"], PAGE)
        assert proc.returncode == 0
        assert out(proc) == "Title\nSub\n"

    def test_results_are_in_document_order(self):
        proc = run_argv(["--css", "h2::text, h1::text"], PAGE)
        assert out(proc) == "Title\nSub\n"

    def test_three_selectors(self):
        proc = run_argv(["--css", "h1::text, p::text, h2::text"], PAGE)
        assert out(proc) == "Title\nOne\nTwo\nSub\n"

    def test_no_space_after_comma(self):
        proc = run_argv(["--css", "h1::text,h2::text"], PAGE)
        assert out(proc) == "Title\nSub\n"

    def test_comma_separated_without_text_is_node_output(self):
        proc = run_argv(["--css", "h1, h2"], PAGE)
        assert proc.returncode == 0
        assert out(proc).strip() == '<h1 class="t">Title</h1>'


# ---------------------------------------------------------------------------
# Spec: "Mixing direct and descendant `::text` modes in one comma-separated
#        CSS query is invalid (stderr message, exit code `1`)."
# Context: CSS Query Mode.
# ---------------------------------------------------------------------------
class TestMixedTextModesInvalid:
    MIXES = ["h1::text, h2 ::text", "h1 ::text, h2::text", "p::text,div ::text"]

    @pytest.mark.parametrize("query", MIXES)
    def test_mixed_modes_exit_one(self, query):
        assert run_argv(["--css", query], PAGE).returncode == 1

    @pytest.mark.parametrize("query", MIXES)
    def test_mixed_modes_write_stderr(self, query):
        assert err(run_argv(["--css", query], PAGE)).strip() != ""

    @pytest.mark.parametrize("query", MIXES)
    def test_mixed_modes_write_nothing_to_stdout(self, query):
        assert out(run_argv(["--css", query], PAGE)) == ""

    # Context: a text selector mixed with a plain one -- see AMBIGUITIES T16.
    def test_text_mixed_with_node_selector_is_invalid(self):
        proc = run_argv(["--css", "h1::text, h2"], PAGE)
        assert proc.returncode == 1
        assert err(proc).strip() != ""


# ---------------------------------------------------------------------------
# Spec: "In CSS mode without text extraction, return XML node output with
#        pretty-print serialization."
# Context: CSS Query Mode. See AMBIGUITIES T15 and T6.
# ---------------------------------------------------------------------------
class TestCssNodeOutput:
    def test_matched_element_serialized_as_xml(self):
        proc = run_argv(["--css", "h1"], PAGE)
        assert out(proc).strip() == '<h1 class="t">Title</h1>'

    def test_nested_element_is_pretty_printed(self):
        proc = run_argv(["--css", "#main"], PAGE)
        lines = out(proc).rstrip("\n").split("\n")
        assert lines[0].startswith("<div")
        assert lines[1].startswith(" ") and lines[1].strip() == "<p>One</p>"
        assert lines[-1] == "</div>"

    def test_attributes_preserved(self):
        proc = run_argv(["--css", "#main"], PAGE)
        assert 'id="main"' in out(proc)

    def test_no_xml_declaration(self):
        proc = run_argv(["--css", "h1"], "<?xml version='1.0'?>" + PAGE)
        assert "<?xml" not in out(proc)

    def test_output_ends_with_single_newline(self):
        text = out(run_argv(["--css", "h1"], PAGE))
        assert text.endswith("\n") and not text.endswith("\n\n")

    def test_tail_text_not_included(self):
        proc = run_argv(["--css", "a"], "<r><a>x</a>TAIL</r>")
        assert "TAIL" not in out(proc)

    # Context: carried over from "output only the first node" -- T15.
    def test_multiple_matches_output_only_first_node(self):
        proc = run_argv(["--css", "p"], PAGE)
        assert "One" in out(proc)
        assert "Two" not in out(proc)

    def test_goes_to_stdout_not_stderr(self):
        proc = run_argv(["--css", "h1"], PAGE)
        assert err(proc) == ""


# ---------------------------------------------------------------------------
# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: CSS Query Mode.
# ---------------------------------------------------------------------------
class TestInvalidCssSelector:
    BAD = ["div..x", "a[", "@#$", "", "p >", "//p", "div[unclosed='x"]

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_css_exits_one(self, query):
        assert run_argv(["--css", query], PAGE).returncode == 1

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_css_writes_stderr(self, query):
        assert err(run_argv(["--css", query], PAGE)).strip() != ""

    @pytest.mark.parametrize("query", BAD)
    def test_invalid_css_writes_nothing_to_stdout(self, query):
        assert out(run_argv(["--css", query], PAGE)) == ""

    def test_invalid_css_message_mentions_css(self):
        proc = run_argv(["--css", "div..x"], PAGE)
        assert "css" in err(proc).lower()

    # Context: only ::text is defined -- see AMBIGUITIES T19.
    def test_unknown_pseudo_element_is_invalid(self):
        proc = run_argv(["--css", "p::before"], PAGE)
        assert proc.returncode == 1
        assert err(proc).strip() != ""

    def test_unknown_pseudo_class_is_invalid(self):
        proc = run_argv(["--css", "p:nonesuch"], PAGE)
        assert proc.returncode == 1

    # Context: ::text is a CSS-mode construct -- see AMBIGUITIES T20.
    def test_text_pseudo_without_css_flag_is_invalid_xpath(self):
        proc = run_argv(["p::text"], PAGE)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()


# ---------------------------------------------------------------------------
# Spec: "Multi-match text output joins lines with `\n`."
# Context: Text Extraction.
# ---------------------------------------------------------------------------
class TestMultiMatchTextJoin:
    def test_two_matches_joined_with_newline(self):
        proc = run_argv(["--css", "p::text"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_flag_based_extraction_joined_with_newline(self):
        proc = run_argv(["-t", "//p"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_descendant_mode_joined_with_newline(self):
        proc = run_argv(["--css", "#main ::text"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_single_match_has_no_embedded_newline(self):
        proc = run_argv(["--css", "h1::text"], PAGE)
        assert out(proc).count("\n") == 1

    def test_line_count_matches_number_of_results(self):
        proc = run_argv(["--css", "-t", "p"], PAGE)
        assert out(proc).rstrip("\n").split("\n") == ["One", "Two"]


# ---------------------------------------------------------------------------
# Spec: "Strip each result and collapse internal whitespace runs to single
#        spaces."
# Context: Text Extraction.
# ---------------------------------------------------------------------------
class TestExtractedTextNormalization:
    def test_leading_and_trailing_whitespace_stripped(self):
        proc = run_argv(["--css", "a::text"], "<r><a>   padded   </a></r>")
        assert out(proc) == "padded\n"

    def test_internal_runs_collapsed(self):
        proc = run_argv(["--css", "a::text"], "<r><a>one     two</a></r>")
        assert out(proc) == "one two\n"

    def test_newlines_and_tabs_collapsed(self):
        proc = run_argv(["--css", "a::text"], "<r><a>one \n\t two\n\nthree</a></r>")
        assert out(proc) == "one two three\n"

    def test_text_flag_strips_and_collapses(self):
        proc = run_argv(["-t", "//a"], "<r><a>  x   y  </a></r>")
        assert out(proc) == "x y\n"

    def test_text_all_strips_and_collapses(self):
        doc = "<r><a>  x   y  <b>  z\n\nw </b></a></r>"
        proc = run_argv(["--text-all", "//a"], doc)
        assert out(proc) == "x y\nz w\n"

    def test_descendant_mode_strips_each_node_separately(self):
        doc = "<r><div> A \n<p>  B  </p> C </div></r>"
        proc = run_argv(["--css", "div ::text"], doc)
        assert out(proc) == "A\nB\nC\n"


# ---------------------------------------------------------------------------
# Spec: "If both `--text` and `--text-all` are present, `--text-all` wins."
# Context: Flag Rules.
# ---------------------------------------------------------------------------
class TestTextAllWins:
    def test_text_then_text_all(self):
        proc = run_argv(["-t", "--text-all", "//div"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_text_all_then_text(self):
        proc = run_argv(["--text-all", "-t", "//div"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_long_form_both(self):
        proc = run_argv(["--text", "--text-all", "//div"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_both_flags_with_css_query(self):
        proc = run_argv(["--css", "-t", "--text-all", "div"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_both_flags_exit_zero(self):
        assert run_argv(["-t", "--text-all", "//div"], MIXED).returncode == 0


# ---------------------------------------------------------------------------
# Spec: "If query already extracts text (`text()` or `::text`), `--text` and
#        `--text-all` are no-op modifiers."
# Context: Flag Rules. See AMBIGUITIES T17.
# ---------------------------------------------------------------------------
class TestFlagsAreNoopForTextQueries:
    def test_text_flag_noop_for_xpath_text_query(self):
        plain = out(run_argv(["//p/text()"], PAGE))
        flagged = out(run_argv(["-t", "//p/text()"], PAGE))
        assert plain == flagged == "One\nTwo\n"

    def test_text_all_flag_noop_for_xpath_text_query(self):
        plain = out(run_argv(["//div/p/text()"], PAGE))
        flagged = out(run_argv(["--text-all", "//div/p/text()"], PAGE))
        assert plain == flagged

    def test_text_all_does_not_expand_xpath_text_query(self):
        # //div/text() selects only the div's own (here: none) text nodes.
        proc = run_argv(["--text-all", "//div/text()"], PAGE)
        assert out(proc) == ""

    def test_text_flag_noop_for_css_text_query(self):
        plain = out(run_argv(["--css", "p::text"], PAGE))
        flagged = out(run_argv(["--css", "-t", "p::text"], PAGE))
        assert plain == flagged == "One\nTwo\n"

    def test_text_all_flag_does_not_upgrade_direct_css_text(self):
        proc = run_argv(["--css", "--text-all", "div::text"], MIXED)
        assert out(proc) == "AC\n"

    def test_text_flag_does_not_downgrade_descendant_css_text(self):
        proc = run_argv(["--css", "-t", "div ::text"], MIXED)
        assert out(proc) == "A\nB\nC\n"

    def test_noop_flags_keep_exit_zero(self):
        assert run_argv(["-t", "//p/text()"], PAGE).returncode == 0


# ===========================================================================
# JSON Input and Auto-Detection
# ===========================================================================

JSON_OBJ = '{"name": "alpha", "count": 2}'
JSON_ARR = '[1, 2, 3]'
NESTED = '{"a": {"b": "x"}, "c": [1, {"d": true}], "e": null}'


# ---------------------------------------------------------------------------
# Spec: "Auto-detect stdin as JSON object/array or XML/HTML."
# Context: Input Auto-Detection. No flag selects the mode; a top-level JSON
# object or array on stdin is converted, anything else is parsed as XML/HTML.
# ---------------------------------------------------------------------------
class TestAutoDetectJson:
    def test_json_object_is_detected(self):
        proc = run_argv(["//name/text()"], JSON_OBJ)
        assert proc.returncode == 0
        assert out(proc) == "alpha\n"

    def test_json_array_is_detected(self):
        proc = run_argv(["//item/text()"], JSON_ARR)
        assert out(proc) == "1\n2\n3\n"

    def test_json_object_with_leading_whitespace(self):
        proc = run_argv(["//name/text()"], "\n\n   " + JSON_OBJ + "\n")
        assert out(proc) == "alpha\n"

    def test_json_pretty_printed_multiline(self):
        doc = '{\n  "name": "alpha",\n  "count": 2\n}\n'
        assert out(run_argv(["//count/text()"], doc)) == "2\n"

    def test_xml_input_still_parsed_as_xml(self):
        proc = run_argv(["//item[@id='2']/text()"], SIMPLE)
        assert out(proc) == "beta\n"

    def test_html_input_still_parsed_as_html(self):
        proc = run_argv(["--css", "p::text"], PAGE)
        assert out(proc) == "One\nTwo\n"

    def test_json_detection_exit_zero(self):
        assert run_argv(["/root"], JSON_OBJ).returncode == 0

    def test_json_detection_writes_nothing_to_stderr(self):
        assert err(run_argv(["//name"], JSON_OBJ)) == ""

    def test_empty_object_is_json(self):
        proc = run_argv(["/root"], "{}")
        assert proc.returncode == 0
        assert out(proc).strip() == "<root/>"

    def test_empty_array_is_json(self):
        proc = run_argv(["/root"], "[]")
        assert proc.returncode == 0
        assert out(proc).strip() == "<root/>"


# ---------------------------------------------------------------------------
# Spec: "Top-level JSON primitives are not accepted as JSON input for this
#        mode; they fall back to XML parsing."
# Context: Input Auto-Detection. Strings/numbers/booleans/null at top level
# are not JSON documents here. See AMBIGUITIES T26.
# ---------------------------------------------------------------------------
class TestTopLevelPrimitivesFallBack:
    @pytest.mark.parametrize("doc", ['"hello"', "42", "1.5", "true", "false", "null"])
    def test_primitive_is_not_json_input(self, doc):
        proc = run_argv(["//*"], doc)
        # Not JSON: parsed as XML, which fails for bare primitive text.
        assert proc.returncode == 1
        assert err(proc) != ""

    @pytest.mark.parametrize("doc", ['"hello"', "42", "true", "null"])
    def test_primitive_error_mentions_xml_or_parse(self, doc):
        message = err(run_argv(["//*"], doc)).lower()
        assert "xml" in message or "parse" in message

    def test_primitive_does_not_become_root_element(self):
        assert out(run_argv(["/root"], "42")) == ""

    def test_number_that_is_also_not_xml_exits_one(self):
        assert run_argv(["/root"], "3.14").returncode == 1

    def test_quoted_xml_string_falls_back(self):
        # A JSON string is a top-level primitive, so XML parsing sees the quotes.
        proc = run_argv(["//a"], '"<a>x</a>"')
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Input that fails JSON detection is parsed as XML/HTML."
# Context: Input Auto-Detection. See AMBIGUITIES T26.
# ---------------------------------------------------------------------------
class TestFallbackToXml:
    def test_malformed_json_object_is_xml_error(self):
        proc = run_argv(["//a"], '{"a": 1')
        assert proc.returncode == 1
        message = err(proc).lower()
        assert "xml" in message or "parse" in message

    def test_trailing_data_after_json_falls_back(self):
        proc = run_argv(["//a"], '{"a": 1} junk')
        assert proc.returncode == 1

    def test_xml_with_braces_in_text_is_xml(self):
        doc = "<root><a>{not json}</a></root>"
        assert out(run_argv(["//a/text()"], doc)) == "{not json}\n"

    def test_document_starting_with_brace_but_valid_xml_later(self):
        # Leading text makes it neither valid JSON nor valid XML.
        assert run_argv(["//a"], "{<a/>").returncode == 1

    def test_empty_input_still_xml_error(self):
        proc = run_argv(["//a"], "")
        assert proc.returncode == 1
        assert "xml" in err(proc).lower() or "parse" in err(proc).lower()

    def test_html_fragment_with_json_like_attribute(self):
        doc = "<html><body><p data-x='{\"k\":1}'>Hi</p></body></html>"
        assert out(run_argv(["--css", "p::text"], doc)) == "Hi\n"


# ---------------------------------------------------------------------------
# Spec: "Wrap converted documents in `<root>`."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestRootWrapper:
    def test_object_document_element_is_root(self):
        assert out(run_argv(["name(/*)"], JSON_OBJ)) == "root\n"

    def test_array_document_element_is_root(self):
        assert out(run_argv(["name(/*)"], JSON_ARR)) == "root\n"

    def test_root_is_the_only_top_level_element(self):
        assert out(run_argv(["count(/*)"], JSON_OBJ)) == "1\n"

    def test_serialized_document_starts_with_root(self):
        assert out(run_argv(["/root"], JSON_OBJ)).startswith("<root>")


# ---------------------------------------------------------------------------
# Spec: "`<root>` must not include `type`."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestRootHasNoType:
    def test_root_type_attribute_absent_for_object(self):
        assert out(run_argv(["/root/@type"], JSON_OBJ)) == ""

    def test_root_type_attribute_absent_for_array(self):
        assert out(run_argv(["/root/@type"], JSON_ARR)) == ""

    def test_root_has_no_attributes_at_all(self):
        assert out(run_argv(["count(/root/@*)"], JSON_OBJ)) == "0\n"

    def test_root_serialization_has_no_type(self):
        assert "type" not in out(run_argv(["/root"], "{}"))


# ---------------------------------------------------------------------------
# Spec: "For top-level objects: keys become direct child elements."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestTopLevelObject:
    def test_keys_are_children_of_root(self):
        assert out(run_argv(["count(/root/*)"], JSON_OBJ)) == "2\n"

    def test_child_names_are_the_keys(self):
        assert out(run_argv(["name(/root/*[1])"], JSON_OBJ)) == "name\n"

    def test_second_child_name(self):
        assert out(run_argv(["name(/root/*[2])"], JSON_OBJ)) == "count\n"

    def test_direct_child_path_selects_value(self):
        assert out(run_argv(["/root/count/text()"], JSON_OBJ)) == "2\n"

    def test_no_item_wrapper_for_objects(self):
        assert out(run_argv(["//item"], JSON_OBJ)) == ""


# ---------------------------------------------------------------------------
# Spec: "For top-level arrays: each entry becomes an `<item>` child of
#        `<root>`."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestTopLevelArray:
    def test_each_entry_is_an_item(self):
        assert out(run_argv(["count(/root/item)"], JSON_ARR)) == "3\n"

    def test_items_are_direct_children_of_root(self):
        assert out(run_argv(["count(/root/*)"], JSON_ARR)) == "3\n"

    def test_entry_order_preserved(self):
        assert out(run_argv(["/root/item/text()"], '["a", "b", "c"]')) == "a\nb\nc\n"

    def test_object_entries_become_items_with_children(self):
        doc = '[{"k": "v"}]'
        assert out(run_argv(["/root/item/k/text()"], doc)) == "v\n"

    def test_empty_array_has_no_items(self):
        assert out(run_argv(["count(/root/item)"], "[]")) == "0\n"


# ---------------------------------------------------------------------------
# Spec: "Object keys become element tag names (case preserved)."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestKeyCasePreserved:
    def test_mixed_case_key_preserved(self):
        doc = '{"CamelCase": 1}'
        assert out(run_argv(["name(/root/*[1])"], doc)) == "CamelCase\n"

    def test_case_distinguishes_sibling_keys(self):
        doc = '{"a": 1, "A": 2}'
        assert out(run_argv(["/root/a/text()"], doc)) == "1\n"
        assert out(run_argv(["/root/A/text()"], doc)) == "2\n"

    def test_upper_case_key_not_matched_by_lower_query(self):
        assert out(run_argv(["/root/name/text()"], '{"NAME": "x"}')) == ""

    def test_underscore_and_dash_keys(self):
        doc = '{"a_b": 1, "c-d": 2}'
        assert out(run_argv(["/root/a_b/text()"], doc)) == "1\n"
        assert out(run_argv(["/root/c-d/text()"], doc)) == "2\n"


# ---------------------------------------------------------------------------
# Spec: "Primitive values map to element text: booleans as `true`/`false`,
#        numbers as minimal string form, null as empty."
# Context: JSON-to-XML Contract. See AMBIGUITIES T25 for exponent-range floats.
# ---------------------------------------------------------------------------
class TestPrimitiveText:
    def test_string_value_text(self):
        assert out(run_argv(["/root/a/text()"], '{"a": "hello"}')) == "hello\n"

    def test_true_is_lowercase(self):
        assert out(run_argv(["/root/a/text()"], '{"a": true}')) == "true\n"

    def test_false_is_lowercase(self):
        assert out(run_argv(["/root/a/text()"], '{"a": false}')) == "false\n"

    def test_null_is_empty_text(self):
        assert out(run_argv(["/root/a/text()"], '{"a": null}')) == ""

    def test_null_element_string_value_is_empty(self):
        # A string() result is a scalar: the value itself is empty.
        assert out(run_argv(["string(/root/a)"], '{"a": null}')).strip() == ""

    def test_null_element_still_exists(self):
        assert out(run_argv(["count(/root/a)"], '{"a": null}')) == "1\n"

    def test_empty_string_value(self):
        assert out(run_argv(["string(/root/a)"], '{"a": ""}')).strip() == ""


# ---------------------------------------------------------------------------
# Spec: "Examples: `1 -> \"1\"`, `1.0 -> \"1\"`, `1.50 -> \"1.5\"`,
#        `0.00012 -> \"0.00012\"`."
# Context: JSON-to-XML Contract, minimal string form of numbers.
# ---------------------------------------------------------------------------
class TestNumberMinimalForm:
    @pytest.mark.parametrize("literal,text", [
        ("1", "1"),
        ("1.0", "1"),
        ("1.50", "1.5"),
        ("0.00012", "0.00012"),
        ("0", "0"),
        ("-3", "-3"),
        ("-2.50", "-2.5"),
        ("3.14", "3.14"),
        ("100.0", "100"),
        ("1e3", "1000"),
    ])
    def test_number_text(self, literal, text):
        doc = '{"a": %s}' % literal
        assert out(run_argv(["/root/a/text()"], doc)) == text + "\n"

    def test_big_integer_kept_exactly(self):
        doc = '{"a": 123456789012345678901234567890}'
        assert out(run_argv(["/root/a/text()"], doc)) == "123456789012345678901234567890\n"

    def test_array_of_numbers(self):
        assert out(run_argv(["/root/item/text()"], "[1.0, 2.50]")) == "1\n2.5\n"


# ---------------------------------------------------------------------------
# Spec: "Every converted element except `<root>` carries `type` in:
#        `str`, `int`, `float`, `bool`, `dict`, `list`, `null`."
# Context: JSON-to-XML Contract. See AMBIGUITIES T24 (1.0 is `float`).
# ---------------------------------------------------------------------------
class TestTypeAttribute:
    @pytest.mark.parametrize("literal,kind", [
        ('"x"', "str"),
        ('""', "str"),
        ("1", "int"),
        ("-7", "int"),
        ("1.5", "float"),
        ("1.0", "float"),
        ("true", "bool"),
        ("false", "bool"),
        ("null", "null"),
        ("{}", "dict"),
        ('{"k": 1}', "dict"),
        ("[]", "list"),
        ("[1]", "list"),
    ])
    def test_type_of_value(self, literal, kind):
        doc = '{"a": %s}' % literal
        assert out(run_argv(["/root/a/@type"], doc)) == kind + "\n"

    def test_item_elements_carry_type(self):
        assert out(run_argv(["/root/item/@type"], JSON_ARR)) == "int\nint\nint\n"

    def test_items_of_mixed_array(self):
        doc = '["x", 1, 1.5, true, null, {}, []]'
        expected = "str\nint\nfloat\nbool\nnull\ndict\nlist\n"
        assert out(run_argv(["/root/item/@type"], doc)) == expected

    def test_nested_elements_carry_type(self):
        assert out(run_argv(["/root/a/b/@type"], NESTED)) == "str\n"

    def test_every_non_root_element_has_a_type(self):
        assert out(run_argv(["count(//*[not(@type)])"], NESTED)) == "1\n"

    def test_all_types_are_from_the_allowed_set(self):
        query = ("count(//*[@type][not(@type='str' or @type='int' or "
                 "@type='float' or @type='bool' or @type='dict' or "
                 "@type='list' or @type='null')])")
        assert out(run_argv([query], NESTED)) == "0\n"

    def test_type_is_queryable_as_predicate(self):
        assert out(run_argv(["//*[@type='bool']/text()"], NESTED)) == "true\n"


# ---------------------------------------------------------------------------
# Spec: "Preserve JSON key order in converted XML."
# Context: JSON-to-XML Contract.
# ---------------------------------------------------------------------------
class TestKeyOrder:
    def test_document_order_matches_json_order(self):
        doc = '{"z": 1, "m": 2, "a": 3}'
        assert out(run_argv(["name(/root/*[1])"], doc)) == "z\n"
        assert out(run_argv(["name(/root/*[3])"], doc)) == "a\n"

    def test_values_follow_key_order(self):
        doc = '{"z": 1, "m": 2, "a": 3}'
        assert out(run_argv(["/root/*/text()"], doc)) == "1\n2\n3\n"

    def test_nested_object_key_order(self):
        doc = '{"outer": {"b": 1, "a": 2}}'
        assert out(run_argv(["/root/outer/*/text()"], doc)) == "1\n2\n"

    def test_order_visible_in_serialization(self):
        text = out(run_argv(["/root"], '{"z": 1, "a": 2}'))
        assert text.index("<z") < text.index("<a")


# ---------------------------------------------------------------------------
# Spec: "JSON keys that are not valid XML element names are invalid input and
#        must produce stderr output with exit code `1` (include terms like
#        `json`/`key`/`invalid`)."
# Context: JSON-to-XML Contract, errors. See AMBIGUITIES T27.
# ---------------------------------------------------------------------------
class TestInvalidKeys:
    BAD = ['{"a b": 1}', '{"1a": 1}', '{"": 1}', '{"a:b": 1}', '{"a/b": 1}',
           '{"@x": 1}', '{"-x": 1}', '{"a<b": 1}']

    @pytest.mark.parametrize("doc", BAD)
    def test_invalid_key_exits_one(self, doc):
        assert run_argv(["//*"], doc).returncode == 1

    @pytest.mark.parametrize("doc", BAD)
    def test_invalid_key_writes_stderr(self, doc):
        assert err(run_argv(["//*"], doc)).strip() != ""

    @pytest.mark.parametrize("doc", BAD)
    def test_invalid_key_message_terms(self, doc):
        message = err(run_argv(["//*"], doc)).lower()
        assert "json" in message or "key" in message or "invalid" in message

    def test_invalid_key_writes_nothing_to_stdout(self):
        assert out(run_argv(["//*"], '{"a b": 1}')) == ""

    def test_invalid_nested_key_also_rejected(self):
        proc = run_argv(["//*"], '{"ok": {"bad key": 1}}')
        assert proc.returncode == 1
        assert err(proc).strip() != ""

    def test_invalid_key_inside_array_entry_rejected(self):
        assert run_argv(["//*"], '[{"bad key": 1}]').returncode == 1

    def test_valid_key_with_dot_accepted(self):
        assert run_argv(["//*"], '{"a.b": 1}').returncode == 0

    def test_valid_key_with_underscore_start_accepted(self):
        assert run_argv(["//*"], '{"_a": 1}').returncode == 0

    def test_valid_key_with_digits_after_start_accepted(self):
        assert out(run_argv(["/root/a1/text()"], '{"a1": 2}')) == "2\n"


# ---------------------------------------------------------------------------
# Spec: JSON-to-XML conversion feeds the existing query pipeline.
# Context: Converted documents are queried exactly like XML input, including
# `--css`, `-t`/`--text` and node serialization. See AMBIGUITIES T30.
# ---------------------------------------------------------------------------
class TestJsonWithExistingFeatures:
    def test_css_selector_on_converted_document(self):
        assert out(run_argv(["--css", "name"], JSON_OBJ)).startswith("<name")

    def test_css_text_pseudo_on_converted_document(self):
        assert out(run_argv(["--css", "name::text"], JSON_OBJ)) == "alpha\n"

    def test_text_flag_on_converted_document(self):
        assert out(run_argv(["-t", "//name"], JSON_OBJ)) == "alpha\n"

    def test_text_all_flag_on_converted_document(self):
        doc = '{"a": {"b": "x", "c": "y"}}'
        assert out(run_argv(["--text-all", "//a"], doc)) == "x\ny\n"

    def test_node_output_is_pretty_printed(self):
        text = out(run_argv(["/root/a"], '{"a": {"b": 1}}'))
        assert text.startswith('<a type="dict">')
        assert "<b" in text

    def test_first_node_only_for_multiple_matches(self):
        assert out(run_argv(["//item"], JSON_ARR)).strip() == '<item type="int">1</item>'

    def test_no_match_on_converted_document_is_silent(self):
        proc = run_argv(["//nope"], JSON_OBJ)
        assert proc.returncode == 0 and out(proc) == "" and err(proc) == ""

    def test_invalid_xpath_on_converted_document(self):
        proc = run_argv(["///"], JSON_OBJ)
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_infile_argument_takes_precedence(self, tmp_path):
        path = tmp_path / "other.json"
        path.write_text('{"name": "from-file"}')
        assert out(run_argv(["//name/text()", str(path)], JSON_OBJ)) == "from-file\n"

    def test_nested_structure_deep_path(self):
        assert out(run_argv(["/root/c/item[2]/d/text()"], NESTED)) == "true\n"

    def test_special_characters_escaped_in_output(self):
        text = out(run_argv(["/root/a"], '{"a": "x<y&z"}'))
        assert "&lt;" in text and "&amp;" in text

    def test_unicode_string_value(self):
        assert out(run_argv(["/root/a/text()"], '{"a": "héllo"}')) == "héllo\n"


# ===========================================================================
# File Input, First-Result, and Compact Output
# ===========================================================================

BOM = b"\xef\xbb\xbf"
MULTI = "<root><item id='1'>alpha</item><item id='2'>beta</item><item id='3'>gamma</item></root>"


def write_file(tmp_path, name, content):
    """Create an input file from text or raw bytes and return its path string."""
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_bytes(content.encode("utf-8"))
    return str(path)


# ---------------------------------------------------------------------------
# Spec: "`-f`, `--first`: return only first result."
# Context: CLI Additions. Both spellings select first-result-only output.
# ---------------------------------------------------------------------------
class TestFirstFlagCli:
    def test_short_flag_returns_only_first_text_result(self):
        assert out(run_argv(["-f", "//item/text()"], MULTI)) == "alpha\n"

    def test_long_flag_returns_only_first_text_result(self):
        assert out(run_argv(["--first", "//item/text()"], MULTI)) == "alpha\n"

    def test_long_flag_matches_short_flag(self):
        short = out(run_argv(["-f", "//item/text()"], MULTI))
        long = out(run_argv(["--first", "//item/text()"], MULTI))
        assert short == long == "alpha\n"

    def test_first_flag_exit_code_zero(self):
        assert run_argv(["-f", "//item/text()"], MULTI).returncode == 0

    def test_first_flag_after_query_is_accepted(self):
        assert out(run_argv(["//item/text()", "--first"], MULTI)) == "alpha\n"

    def test_without_first_all_text_results_are_printed(self):
        assert out(run_argv(["//item/text()"], MULTI)) == "alpha\nbeta\ngamma\n"

    def test_first_flag_appears_in_help(self):
        proc = run_argv(["--help"])
        assert b"--first" in proc.stdout


# ---------------------------------------------------------------------------
# Spec: "`-c`, `--compact`: compact output mode."
# Context: CLI Additions. Both spellings select compact output mode.
# ---------------------------------------------------------------------------
class TestCompactFlagCli:
    DOC = "<root><a><b>x</b></a></root>"

    def test_short_flag_accepted(self):
        assert run_argv(["-c", "/root/a"], self.DOC).returncode == 0

    def test_long_flag_accepted(self):
        assert run_argv(["--compact", "/root/a"], self.DOC).returncode == 0

    def test_short_and_long_agree(self):
        assert out(run_argv(["-c", "/root/a"], self.DOC)) == out(
            run_argv(["--compact", "/root/a"], self.DOC)
        )

    def test_compact_flag_appears_in_help(self):
        proc = run_argv(["--help"])
        assert b"--compact" in proc.stdout

    # Context: -c must not collide with the existing --css long option.
    def test_compact_short_flag_does_not_enable_css(self):
        proc = run_argv(["-c", "#main"], "<div id='main'/>")
        assert proc.returncode == 1
        assert "xpath" in err(proc).lower()

    def test_compact_and_css_combine(self):
        proc = run_argv(["-c", "--css", "a"], "<root><a><b>x</b></a></root>")
        assert proc.returncode == 0
        assert out(proc) == "<a><b>x</b></a>\n"


# ---------------------------------------------------------------------------
# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: Input Source. When a file argument is given the file is the
# document; the bytes on stdin are not used.
# ---------------------------------------------------------------------------
class TestInfilePrecedence:
    def test_file_contents_win_over_stdin(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>from-file</a></root>")
        assert out(run_argv(["//a/text()", str(path)], "<root><a>from-stdin</a></root>")) == "from-file\n"

    def test_stdin_content_is_not_queried(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>file</a></root>")
        proc = run_argv(["//b/text()", path], "<root><b>stdin</b></root>")
        assert proc.returncode == 0
        assert out(proc) == ""

    def test_file_used_when_stdin_is_empty(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>only-file</a></root>")
        assert out(run_argv(["//a/text()", path], "")) == "only-file\n"

    def test_stdin_still_used_without_infile(self):
        assert out(run_argv(["//a/text()"], "<root><a>stdin</a></root>")) == "stdin\n"

    def test_file_used_when_stdin_is_malformed(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>ok</a></root>")
        proc = run_argv(["//a/text()", path], "<not-xml")
        assert proc.returncode == 0
        assert out(proc) == "ok\n"

    def test_flags_apply_to_file_input(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", MULTI)
        assert out(run_argv(["-f", "//item/text()", path], "")) == "alpha\n"

    def test_css_mode_reads_file(self, tmp_path):
        path = write_file(tmp_path, "doc.html", "<div><p>One</p></div>")
        assert out(run_argv(["--css", "-t", "p", path], "")) == "One\n"


# ---------------------------------------------------------------------------
# Spec: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: Input Source. A third and later positional is accepted silently.
# ---------------------------------------------------------------------------
class TestExtraPositionalsIgnored:
    def test_third_positional_is_ignored(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>file</a></root>")
        proc = run_argv(["//a/text()", path, "extra"], "")
        assert proc.returncode == 0
        assert out(proc) == "file\n"

    def test_many_extra_positionals_ignored(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>file</a></root>")
        proc = run_argv(["//a/text()", path, "x", "y", "z"], "")
        assert proc.returncode == 0
        assert out(proc) == "file\n"

    def test_extra_positional_file_is_not_read(self, tmp_path):
        first = write_file(tmp_path, "one.xml", "<root><a>one</a></root>")
        second = write_file(tmp_path, "two.xml", "<root><a>two</a></root>")
        assert out(run_argv(["//a/text()", first, second], "")) == "one\n"

    def test_extra_positional_may_be_missing_file(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>file</a></root>")
        proc = run_argv(["//a/text()", path, "/no/such/file.xml"], "")
        assert proc.returncode == 0
        assert out(proc) == "file\n"

    def test_extra_positional_with_stdin_input(self):
        # Context: QUERY plus extras but no readable INFILE is still an error
        # for the INFILE slot -- see AMBIGUITIES T36.
        proc = run_argv(["//a/text()", "/no/such/file.xml", "extra"], "<root><a>x</a></root>")
        assert proc.returncode == 1

    # Context: only positionals are ignored; unknown options still fail.
    def test_unknown_option_is_still_an_error(self):
        proc = run_argv(["--bogus", "//a"], "<root><a>x</a></root>")
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Spec: "Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed."
# Context: Input Source. File bytes are UTF-8; a leading BOM must not break
# parsing or detection.
# ---------------------------------------------------------------------------
class TestInfileDecoding:
    def test_utf8_content_decoded(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>héllo</a></root>")
        assert out(run_argv(["//a/text()", path], "")) == "héllo\n"

    def test_utf8_multibyte_beyond_bmp(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>\U0001F600</a></root>")
        assert out(run_argv(["//a/text()", path], "")) == "\U0001F600\n"

    def test_bom_allowed_before_xml(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", BOM + b"<root><a>x</a></root>")
        proc = run_argv(["//a/text()", path], "")
        assert proc.returncode == 0
        assert out(proc) == "x\n"

    def test_bom_is_not_part_of_output(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", BOM + b"<root><a>x</a></root>")
        assert "﻿" not in out(run_argv(["//a/text()", path], ""))

    def test_bom_allowed_before_json(self, tmp_path):
        path = write_file(tmp_path, "doc.json", BOM + b'{"name": "alpha"}')
        proc = run_argv(["//name/text()", path], "")
        assert proc.returncode == 0
        assert out(proc) == "alpha\n"

    def test_bom_with_xml_declaration(self, tmp_path):
        path = write_file(
            tmp_path, "doc.xml", BOM + b"<?xml version='1.0' encoding='utf-8'?><a>x</a>"
        )
        assert out(run_argv(["//a/text()", path], "")) == "x\n"

    # Context: bytes that are not UTF-8 are not decodable -- see AMBIGUITIES T34.
    def test_non_utf8_file_is_an_error(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", b"<root><a>\xff\xfe</a></root>")
        proc = run_argv(["//a/text()", path], "")
        assert proc.returncode == 1
        assert err(proc) != ""


# ---------------------------------------------------------------------------
# Spec: "Apply JSON auto-detection to file input: treat as JSON object/array
# when detected, otherwise parse as XML/HTML."
# Context: Input Source. File input goes through the same detection as stdin.
# ---------------------------------------------------------------------------
class TestFileJsonAutoDetection:
    def test_json_object_file_detected(self, tmp_path):
        path = write_file(tmp_path, "doc.json", '{"name": "alpha", "count": 2}')
        assert out(run_argv(["//name/text()", path], "")) == "alpha\n"

    def test_json_object_file_wrapped_in_root(self, tmp_path):
        path = write_file(tmp_path, "doc.json", '{"name": "alpha"}')
        assert out(run_argv(["/root/name/text()", path], "")) == "alpha\n"

    def test_json_array_file_detected(self, tmp_path):
        path = write_file(tmp_path, "doc.json", "[1, 2, 3]")
        assert out(run_argv(["/root/item[2]/text()", path], "")) == "2\n"

    def test_json_file_carries_type_attribute(self, tmp_path):
        path = write_file(tmp_path, "doc.json", '{"n": 1}')
        assert out(run_argv(["/root/n/@type", path], "")) == "int\n"

    def test_xml_file_still_parsed_as_xml(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", "<root><a>x</a></root>")
        assert out(run_argv(["//a/text()", path], "")) == "x\n"

    def test_html_file_parsed_as_html(self, tmp_path):
        path = write_file(tmp_path, "doc.html", "<html><body><p>One<p>Two</body></html>")
        assert out(run_argv(["-t", "//p[1]", path], "")) == "One\n"

    def test_json_primitive_file_is_not_json_input(self, tmp_path):
        # Context: top-level primitives fall back to XML parsing (AMBIGUITIES T26).
        path = write_file(tmp_path, "doc.json", '"just a string"')
        proc = run_argv(["//a", path], "")
        assert proc.returncode == 1

    def test_invalid_key_in_json_file_is_an_error(self, tmp_path):
        path = write_file(tmp_path, "doc.json", '{"bad key": 1}')
        proc = run_argv(["//*", path], "")
        assert proc.returncode == 1
        assert "json" in err(proc).lower() or "key" in err(proc).lower()


# ---------------------------------------------------------------------------
# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: Input Source. A file argument that cannot be read is a fatal error.
# ---------------------------------------------------------------------------
class TestMissingFile:
    def test_missing_file_exits_1(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path / "nope.xml")], "")
        assert proc.returncode == 1

    def test_missing_file_writes_stderr(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path / "nope.xml")], "")
        assert err(proc).strip() != ""

    def test_missing_file_writes_nothing_to_stdout(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path / "nope.xml")], "")
        assert out(proc) == ""

    def test_missing_file_message_mentions_file(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path / "nope.xml")], "")
        assert "nope.xml" in err(proc) or "file" in err(proc).lower()

    def test_missing_file_does_not_fall_back_to_stdin(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path / "nope.xml")], "<root><a>x</a></root>")
        assert proc.returncode == 1
        assert out(proc) == ""

    def test_directory_as_infile_is_an_error(self, tmp_path):
        proc = run_argv(["//a/text()", str(tmp_path)], "")
        assert proc.returncode == 1
        assert err(proc).strip() != ""

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses file modes"
    )
    def test_unreadable_file_is_an_error(self, tmp_path):
        path = tmp_path / "secret.xml"
        path.write_text("<root><a>x</a></root>")
        path.chmod(0o000)
        try:
            proc = run_argv(["//a/text()", str(path)], "")
        finally:
            path.chmod(0o644)
        assert proc.returncode == 1
        assert err(proc).strip() != ""

    # Context: the input error is reported before the query is evaluated
    # -- see AMBIGUITIES T8.
    def test_missing_file_reported_before_invalid_xpath(self, tmp_path):
        proc = run_argv(["///", str(tmp_path / "nope.xml")], "")
        assert proc.returncode == 1
        assert "xpath" not in err(proc).lower()

    def test_empty_file_is_an_input_error(self, tmp_path):
        path = write_file(tmp_path, "empty.xml", "")
        proc = run_argv(["//a", path], "")
        assert proc.returncode == 1
        assert "xml" in err(proc).lower() or "parse" in err(proc).lower()


# ---------------------------------------------------------------------------
# Spec: "`--first` applies across text, attribute, and XML-node results."
# Context: Output Rules. One flag, one behavior for every result kind.
# ---------------------------------------------------------------------------
class TestFirstAppliesEverywhere:
    def test_first_text_result(self):
        assert out(run_argv(["--first", "//item/text()"], MULTI)) == "alpha\n"

    def test_first_attribute_result(self):
        assert out(run_argv(["--first", "//item/@id"], MULTI)) == "1\n"

    def test_first_xml_node_result(self):
        text = out(run_argv(["--first", "//item"], MULTI))
        assert text.startswith('<item id="1">')
        assert "beta" not in text

    def test_first_node_result_matches_default_node_output(self):
        # Context: node output already emits only the first node, so --first
        # is a no-op there -- see AMBIGUITIES T31.
        assert out(run_argv(["--first", "//item"], MULTI)) == out(run_argv(["//item"], MULTI))

    def test_first_with_css_node_output(self):
        doc = "<root><p>One</p><p>Two</p></root>"
        text = out(run_argv(["--css", "--first", "p"], doc))
        assert "One" in text and "Two" not in text

    def test_first_with_text_flag(self):
        assert out(run_argv(["-f", "-t", "//item"], MULTI)) == "alpha\n"

    def test_first_with_css_text_pseudo(self):
        doc = "<root><p>One</p><p>Two</p></root>"
        assert out(run_argv(["--css", "-f", "p::text"], doc)) == "One\n"

    # Context: with descendant text one element yields several lines; --first
    # keeps exactly one result line -- see AMBIGUITIES T32.
    def test_first_with_descendant_text_keeps_one_line(self):
        doc = "<root><div>A<span>B</span>C</div><div>D</div></root>"
        assert out(run_argv(["--first", "--text-all", "//div"], doc)) == "A\n"

    def test_first_with_css_descendant_text_keeps_one_line(self):
        doc = "<root><div>A<span>B</span>C</div></root>"
        assert out(run_argv(["--css", "--first", "div ::text"], doc)) == "A\n"

    def test_first_on_single_result_is_unchanged(self):
        assert out(run_argv(["--first", "//item[1]/text()"], MULTI)) == "alpha\n"

    def test_first_on_scalar_result(self):
        assert out(run_argv(["--first", "count(//item)"], MULTI)) == "3\n"

    def test_first_takes_document_order(self):
        assert out(run_argv(["--first", "//item[@id>'1']/text()"], MULTI)) == "beta\n"

    def test_first_on_json_input(self):
        assert out(run_argv(["--first", "/root/item/text()"], "[1, 2, 3]")) == "1\n"

    def test_first_on_file_input(self, tmp_path):
        path = write_file(tmp_path, "doc.xml", MULTI)
        assert out(run_argv(["--first", "//item/@id", path], "")) == "1\n"


# ---------------------------------------------------------------------------
# Spec: "`--first` with no matches remains silent (no output)."
# Context: Output Rules. The no-match rule is unchanged by the flag.
# ---------------------------------------------------------------------------
class TestFirstNoMatch:
    def test_no_match_writes_nothing(self):
        proc = run_argv(["--first", "//nope"], MULTI)
        assert out(proc) == ""

    def test_no_match_writes_no_stderr(self):
        proc = run_argv(["--first", "//nope"], MULTI)
        assert err(proc) == ""

    def test_no_match_exit_code_zero(self):
        assert run_argv(["--first", "//nope"], MULTI).returncode == 0

    def test_no_match_text_query_silent(self):
        proc = run_argv(["-f", "//nope/text()"], MULTI)
        assert proc.returncode == 0 and out(proc) == "" and err(proc) == ""

    def test_no_match_attribute_query_silent(self):
        proc = run_argv(["-f", "//item/@missing"], MULTI)
        assert proc.returncode == 0 and out(proc) == ""

    def test_no_match_css_silent(self):
        proc = run_argv(["--css", "-f", "article"], MULTI)
        assert proc.returncode == 0 and out(proc) == "" and err(proc) == ""

    def test_no_match_text_extraction_silent(self):
        doc = "<root><div><span/></div></root>"
        proc = run_argv(["-f", "-t", "//div"], doc)
        assert proc.returncode == 0 and out(proc) == ""


# ---------------------------------------------------------------------------
# Spec: "`--compact` affects XML serialization only: compact XML output has no
# added pretty-print formatting."
# Context: Output Rules. Node output loses the pretty-printer; text and
# attribute output are untouched.
# ---------------------------------------------------------------------------
class TestCompactXmlSerialization:
    NESTED_DOC = "<root><a><b>x</b></a></root>"

    def test_compact_node_is_single_line(self):
        assert out(run_argv(["-c", "/root/a"], self.NESTED_DOC)) == "<a><b>x</b></a>\n"

    def test_default_node_output_is_pretty_printed(self):
        text = out(run_argv(["/root/a"], self.NESTED_DOC))
        assert "\n" in text.rstrip("\n")
        assert "  <b>x</b>" in text

    def test_compact_has_no_indentation(self):
        text = out(run_argv(["-c", "/root/a"], self.NESTED_DOC))
        assert "  " not in text

    def test_compact_keeps_attributes(self):
        assert out(run_argv(["-c", "//item[1]"], MULTI)) == '<item id="1">alpha</item>\n'

    def test_compact_keeps_trailing_newline(self):
        assert out(run_argv(["-c", "/root/a"], self.NESTED_DOC)).endswith("\n")

    def test_compact_single_element_matches_default(self):
        doc = "<root><a>x</a></root>"
        assert out(run_argv(["-c", "/root/a"], doc)) == out(run_argv(["/root/a"], doc))

    # Context: "no *added* formatting" -- whitespace already in the document is
    # part of the node's content and is preserved (AMBIGUITIES T33).
    def test_compact_preserves_source_whitespace(self):
        doc = "<root>\n  <a>\n    <b>x</b>\n  </a>\n</root>"
        text = out(run_argv(["-c", "/root/a"], doc))
        assert text == "<a>\n    <b>x</b>\n  </a>\n"

    def test_compact_does_not_change_text_output(self):
        assert out(run_argv(["-c", "//item/text()"], MULTI)) == "alpha\nbeta\ngamma\n"

    def test_compact_does_not_change_attribute_output(self):
        assert out(run_argv(["-c", "//item/@id"], MULTI)) == "1\n2\n3\n"

    def test_compact_does_not_change_text_extraction(self):
        assert out(run_argv(["-c", "-t", "//item"], MULTI)) == "alpha\nbeta\ngamma\n"

    def test_compact_does_not_change_css_text(self):
        doc = "<root><div>A<span>B</span></div></root>"
        assert out(run_argv(["-c", "--css", "div ::text"], doc)) == "A\nB\n"

    def test_compact_does_not_change_scalar_output(self):
        assert out(run_argv(["-c", "count(//item)"], MULTI)) == "3\n"

    def test_compact_node_still_first_only(self):
        text = out(run_argv(["-c", "//item"], MULTI))
        assert text == '<item id="1">alpha</item>\n'

    def test_compact_with_first_flag(self):
        assert out(run_argv(["-c", "-f", "//item"], MULTI)) == '<item id="1">alpha</item>\n'

    def test_compact_no_match_is_silent(self):
        proc = run_argv(["-c", "//nope"], MULTI)
        assert proc.returncode == 0 and out(proc) == "" and err(proc) == ""

    def test_compact_escapes_special_characters(self):
        doc = "<root><a>x&lt;y&amp;z</a></root>"
        assert out(run_argv(["-c", "/root/a"], doc)) == "<a>x&lt;y&amp;z</a>\n"

    def test_compact_empty_element(self):
        assert out(run_argv(["-c", "/root/a"], "<root><a/></root>")) == "<a/>\n"

    def test_compact_drops_tail_text(self):
        text = out(run_argv(["-c", "/root/a"], "<root><a>x</a>tail</root>"))
        assert text == "<a>x</a>\n"


# ---------------------------------------------------------------------------
# Spec: "For JSON-derived input, `--compact` still applies to resulting XML
# output."
# Context: Output Rules. Converted JSON documents serialize compactly too.
# ---------------------------------------------------------------------------
class TestCompactWithJsonInput:
    def test_compact_json_object_node(self):
        assert out(run_argv(["-c", "/root/a"], '{"a": {"b": 1}}')) == (
            '<a type="dict"><b type="int">1</b></a>\n'
        )

    def test_default_json_node_output_is_pretty_printed(self):
        text = out(run_argv(["/root/a"], '{"a": {"b": 1}}'))
        assert "\n" in text.rstrip("\n")

    def test_compact_json_root_node(self):
        assert out(run_argv(["-c", "/root"], '{"a": 1}')) == (
            '<root><a type="int">1</a></root>\n'
        )

    def test_compact_json_array_node(self):
        assert out(run_argv(["-c", "/root"], "[1, 2]")) == (
            '<root><item type="int">1</item><item type="int">2</item></root>\n'
        )

    def test_compact_json_nested_array(self):
        assert out(run_argv(["-c", "/root/a"], '{"a": [true, null]}')) == (
            '<a type="list"><item type="bool">true</item><item type="null"/></a>\n'
        )

    def test_compact_json_from_file(self, tmp_path):
        path = write_file(tmp_path, "doc.json", '{"a": {"b": 1}}')
        assert out(run_argv(["-c", "/root/a", path], "")) == (
            '<a type="dict"><b type="int">1</b></a>\n'
        )

    def test_compact_json_with_first(self):
        assert out(run_argv(["-c", "-f", "/root/item"], "[1, 2]")) == (
            '<item type="int">1</item>\n'
        )

    def test_compact_json_css_node_output(self):
        assert out(run_argv(["-c", "--css", "a"], '{"a": {"b": 1}}')) == (
            '<a type="dict"><b type="int">1</b></a>\n'
        )

    def test_compact_json_text_output_unchanged(self):
        assert out(run_argv(["-c", "/root/a/text()"], '{"a": "x"}')) == "x\n"
