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
# Context: CLI. Second positional is parsed but must not change behavior.
# ---------------------------------------------------------------------------
class TestInfileIgnored:
    def test_infile_accepted(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<other><item>IGNORED</item></other>")
        proc = run("//item/text()", SIMPLE, str(path))
        assert proc.returncode == 0

    def test_infile_contents_not_used(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<other><item>IGNORED</item></other>")
        proc = run("//item/text()", SIMPLE, str(path))
        assert out(proc) == "alpha\nbeta\n"
        assert "IGNORED" not in out(proc)

    def test_nonexistent_infile_still_works(self):
        proc = run("//item/text()", SIMPLE, "/no/such/file.xml")
        assert proc.returncode == 0
        assert out(proc) == "alpha\nbeta\n"


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

    def test_css_query_with_infile_positional(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<other/>")
        proc = run_argv(["--css", "p", str(path)], PAGE)
        assert proc.returncode == 0
        assert "One" in out(proc)

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
