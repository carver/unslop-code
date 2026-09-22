"""Spec tests for xjq.py, one section per phrase of the specification."""

import subprocess
import sys
from pathlib import Path

import pytest

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"

DOC = b"""<Root>
  <Item id="a">first</Item>
  <Item id="b">second</Item>
</Root>"""


def run(*args, stdin=b""):
    """Invoke `python xjq.py <args>` with `stdin` piped in."""
    return subprocess.run(
        [sys.executable, str(XJQ), *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def out(result):
    return result.stdout.decode()


def err(result):
    return result.stderr.decode()


# --- CLI: "Implement executable `xjq.py`" ---------------------------------


def test_script_exists():
    assert XJQ.is_file()


def test_script_runs_as_python_program():
    # `python xjq.py [OPTIONS] QUERY [INFILE]`
    result = run("//Item/text()", stdin=DOC)
    assert result.returncode == 0


# --- CLI: "`QUERY`: XPath expression." ------------------------------------


def test_query_is_the_first_positional_argument():
    result = run("//Item[@id='b']/text()", stdin=DOC)
    assert out(result) == "second"


def test_query_argument_is_required():
    # QUERY is not optional in the usage line, so omitting it is a usage error.
    result = run(stdin=DOC)
    assert result.returncode != 0


# --- CLI: "`INFILE`: accepted positional argument but not used." ----------


def test_infile_is_accepted(tmp_path):
    infile = tmp_path / "other.xml"
    infile.write_text("<Root><Item>from file</Item></Root>")
    result = run("//Item/text()", str(infile), stdin=DOC)
    assert result.returncode == 0


def test_infile_content_is_ignored(tmp_path):
    # Accepted but not used: the document still comes from stdin.
    infile = tmp_path / "other.xml"
    infile.write_text("<Root><Item>from file</Item></Root>")
    result = run("//Item/text()", str(infile), stdin=DOC)
    assert out(result) == "first\nsecond"


def test_missing_infile_path_is_not_an_error():
    # The argument is never opened, so a non-existent path is harmless.
    result = run("//Item/text()", "/no/such/file.xml", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == "first\nsecond"


# --- CLI: "Input source: stdin." ------------------------------------------


def test_document_is_read_from_stdin():
    result = run("//a/text()", stdin=b"<r><a>piped</a></r>")
    assert out(result) == "piped"


# --- Behavior: "Parse stdin as XML/HTML ..." ------------------------------


def test_parses_xml_document():
    result = run("//Item/@id", stdin=DOC)
    assert out(result) == "a\nb"


def test_parses_html_shaped_document():
    html = b"<html><body><p class='x'>hello</p></body></html>"
    result = run("//p/text()", stdin=html)
    assert out(result) == "hello"


# --- Behavior: "... using case-sensitive element matching." ---------------


def test_element_matching_is_case_sensitive_on_hit():
    result = run("//Item/text()", stdin=DOC)
    assert out(result) == "first\nsecond"


def test_element_matching_is_case_sensitive_on_miss():
    # A lowercased name must not match the `<Item>` elements.
    result = run("//item/text()", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == ""


def test_html_tag_names_keep_their_case():
    result = run("//DIV/text()", stdin=b"<HTML><DIV>kept</DIV></HTML>")
    assert out(result) == "kept"


# --- Behavior: "Evaluate `QUERY` with XPath 1.0." -------------------------


def test_supports_predicates():
    result = run("//Item[2]/text()", stdin=DOC)
    assert out(result) == "second"


def test_supports_string_functions():
    result = run("//Item[contains(text(),'sec')]/@id", stdin=DOC)
    assert out(result) == "b"


def test_supports_string_conversion():
    result = run("string(//Item[1])", stdin=DOC)
    assert out(result) == "first"


def test_supports_union_of_attribute_results():
    result = run("//Item/@id | //Item/text()", stdin=DOC)
    assert result.returncode == 0
    assert out(result).splitlines() == ["a", "first", "b", "second"]


def test_supports_numeric_functions():
    # Scalar (non node-set) results are formatted with XPath 1.0 string()
    # semantics, so an integral number has no decimal part -- see AMBIGUITIES T4.
    result = run("count(//Item)", stdin=DOC)
    assert out(result) == "2"


def test_supports_boolean_functions():
    # See AMBIGUITIES T4.
    result = run("boolean(//Item)", stdin=DOC)
    assert out(result) == "true"


# --- Behavior: "Exit code `0` on successful execution, ..." ---------------


def test_exit_code_zero_on_success():
    result = run("//Item/text()", stdin=DOC)
    assert result.returncode == 0


# --- Behavior: "... including zero matches." ------------------------------


def test_exit_code_zero_on_zero_matches():
    result = run("//Missing", stdin=DOC)
    assert result.returncode == 0


# --- Output: "Text/attribute results: strip each result, ..." -------------


def test_text_result_is_stripped():
    result = run("//a/text()", stdin=b"<r><a>   padded   </a></r>")
    assert out(result) == "padded"


def test_attribute_result_is_stripped():
    result = run("//a/@href", stdin=b'<r><a href="  /x  "/></r>')
    assert out(result) == "/x"


# --- Output: "... collapse internal whitespace runs to single spaces, ..." -


def test_internal_spaces_are_collapsed():
    result = run("//a/text()", stdin=b"<r><a>hello    world</a></r>")
    assert out(result) == "hello world"


def test_internal_newlines_and_tabs_are_collapsed():
    result = run("//a/text()", stdin=b"<r><a>\n hello \t\n world \n</a></r>")
    assert out(result) == "hello world"


def test_attribute_whitespace_is_collapsed():
    result = run("//a/@title", stdin=b'<r><a title="a   b\tc"/></r>')
    assert out(result) == "a b c"


# --- Output: "... then join results with each on a newline." --------------


def test_multiple_text_results_are_joined_with_newlines():
    result = run("//a/text()", stdin=b"<r><a>one</a><a>two</a><a>three</a></r>")
    assert out(result) == "one\ntwo\nthree"


def test_multiple_attribute_results_are_joined_with_newlines():
    result = run("//a/@id", stdin=b'<r><a id="1"/><a id="2"/></r>')
    assert out(result) == "1\n2"


# --- Output: "No trailing newline." ---------------------------------------


def test_single_text_result_has_no_trailing_newline():
    result = run("//a/text()", stdin=b"<r><a>solo</a></r>")
    assert out(result) == "solo"
    assert not out(result).endswith("\n")


def test_joined_results_have_no_trailing_newline():
    result = run("//a/text()", stdin=b"<r><a>one</a><a>two</a></r>")
    assert not out(result).endswith("\n")


# --- Output: "XML node results: pretty-print serialized XML" --------------


def test_element_result_is_serialized_as_xml():
    result = run("//Item[1]", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="a">first</Item>'


def test_element_result_is_pretty_printed():
    doc = b"<root><parent><child a='1'>hi</child></parent></root>"
    result = run("//parent", stdin=doc)
    assert out(result).rstrip("\n") == '<parent>\n  <child a="1">hi</child>\n</parent>'


def test_pretty_print_reindents_source_whitespace():
    # Indentation is rebuilt from the tree, not copied from the input -- see
    # AMBIGUITIES T2.
    doc = b"<root><parent>\n        <child/>\n</parent></root>"
    result = run("//parent", stdin=doc)
    assert out(result).rstrip("\n") == "<parent>\n  <child/>\n</parent>"


def test_element_result_excludes_following_text():
    # The tail text after the element is not part of the node -- see AMBIGUITIES T7.
    result = run("//a", stdin=b"<r><a>keep</a>tail text</r>")
    assert out(result).rstrip("\n") == "<a>keep</a>"


def test_root_element_can_be_selected():
    result = run("/Root", stdin=b"<Root><Item/></Root>")
    assert out(result).rstrip("\n") == "<Root>\n  <Item/>\n</Root>"


# --- Output: "... when multiple XML nodes match, output only the first" ----


def test_only_first_of_multiple_element_results_is_printed():
    result = run("//Item", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="a">first</Item>'


def test_first_element_result_is_document_order_first():
    doc = b'<r><a n="1"/><a n="2"/><a n="3"/></r>'
    assert out(run("//a", stdin=doc)).rstrip("\n") == '<a n="1"/>'


def test_exit_code_zero_for_element_result():
    assert run("//Item", stdin=DOC).returncode == 0


# --- Output: "No-match output: write nothing to stdout/stderr." -----------


def test_no_match_writes_nothing_to_stdout():
    result = run("//Missing", stdin=DOC)
    assert out(result) == ""


def test_no_match_writes_nothing_to_stderr():
    result = run("//Missing", stdin=DOC)
    assert err(result) == ""


def test_no_matching_attribute_writes_nothing():
    result = run("//Item/@missing", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == ""
    assert err(result) == ""


# --- Errors: "Invalid XPath: stderr message, exit code `1`" ---------------


# Validity is whatever the XPath 1.0 engine accepts -- see AMBIGUITIES T10.
@pytest.mark.parametrize("query", ["//a[", "//a/[1]", "not-a-function()", "//"])
def test_invalid_xpath_exits_one(query):
    result = run(query, stdin=DOC)
    assert result.returncode == 1


def test_invalid_xpath_writes_to_stderr():
    result = run("//a[", stdin=DOC)
    assert err(result).strip() != ""


def test_invalid_xpath_writes_nothing_to_stdout():
    result = run("//a[", stdin=DOC)
    assert out(result) == ""


# --- Errors: "message should reference `xpath`" ---------------------------


def test_invalid_xpath_message_references_xpath():
    result = run("//a[", stdin=DOC)
    assert "xpath" in err(result).lower()


def test_undefined_namespace_prefix_is_an_xpath_error():
    result = run("//ns:Item", stdin=DOC)
    assert result.returncode == 1
    assert "xpath" in err(result).lower()


# --- Errors: "Malformed/empty XML input: stderr message, exit code `1`" ---


def test_malformed_xml_exits_one():
    result = run("//a", stdin=b"<r><a></r>")
    assert result.returncode == 1


def test_unclosed_root_exits_one():
    result = run("//a", stdin=b"<r><a>text")
    assert result.returncode == 1


def test_non_xml_input_exits_one():
    result = run("//a", stdin=b"this is not xml at all")
    assert result.returncode == 1


def test_empty_input_exits_one():
    result = run("//a", stdin=b"")
    assert result.returncode == 1


def test_whitespace_only_input_exits_one():
    result = run("//a", stdin=b"   \n\t  ")
    assert result.returncode == 1


def test_malformed_xml_writes_nothing_to_stdout():
    result = run("//a", stdin=b"<r><a></r>")
    assert out(result) == ""


# --- Errors: "message should reference `xml`/`parse`" ---------------------


@pytest.mark.parametrize("payload", [b"<r><a></r>", b"", b"   ", b"nonsense"])
def test_xml_error_message_references_xml_or_parse(payload):
    result = run("//a", stdin=payload)
    message = err(result).lower()
    assert message.strip() != ""
    assert "xml" in message or "parse" in message


def test_input_error_precedes_query_error():
    # Both are broken: parsing happens first -- see AMBIGUITIES T9.
    result = run("//a[", stdin=b"<r><a></r>")
    assert result.returncode == 1
    assert "xml" in err(result).lower() or "parse" in err(result).lower()
