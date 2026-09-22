"""Spec tests for CSS selectors and text extraction, one section per phrase."""

import subprocess
import sys
from pathlib import Path

import pytest

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"

DOC = b"""<Root>
  <Item id="a" class="one">first</Item>
  <Item id="b" class="two">second</Item>
</Root>"""

MIXED = b"<Root><div>Hello <b>World</b>!</div><div>plain</div></Root>"


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


# --- CLI: "`--css`: interpret `QUERY` as CSS selector." -------------------


def test_css_flag_selects_by_tag_name():
    result = run("--css", "Item", stdin=DOC)
    assert result.returncode == 0
    assert out(result).rstrip("\n") == '<Item id="a" class="one">first</Item>'


def test_css_flag_selects_by_class():
    result = run("--css", ".two", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="b" class="two">second</Item>'


def test_css_flag_selects_by_id():
    result = run("--css", "#a", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="a" class="one">first</Item>'


def test_css_flag_selects_by_attribute():
    result = run("--css", "[id=b]", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="b" class="two">second</Item>'


def test_css_descendant_combinator():
    result = run("--css", "-t", "div b", stdin=MIXED)
    assert out(result) == "World"


def test_css_child_combinator():
    result = run("--css", "-t", "Root > Item", stdin=DOC)
    assert out(result) == "first\nsecond"


def test_css_element_matching_is_case_sensitive():
    result = run("--css", "item", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == ""


def test_query_is_xpath_without_the_css_flag():
    # `.two` is a CSS class selector but not a valid XPath expression -- see
    # AMBIGUITIES T18.
    result = run(".two", stdin=DOC)
    assert result.returncode == 1


def test_css_query_with_no_match_exits_zero_and_prints_nothing():
    result = run("--css", "nope", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == ""
    assert err(result) == ""


# --- CLI: "`-t`, `--text`: direct text extraction from matched elements" --


def test_text_flag_extracts_text_of_css_matches():
    result = run("--css", "-t", "Item", stdin=DOC)
    assert out(result) == "first\nsecond"


def test_long_text_flag_is_equivalent():
    assert out(run("--css", "--text", "Item", stdin=DOC)) == "first\nsecond"


def test_text_flag_applies_to_xpath_matches():
    # The flags are CLI-wide, not CSS-only -- see AMBIGUITIES T16.
    result = run("-t", "//Item", stdin=DOC)
    assert out(result) == "first\nsecond"


def test_text_flag_excludes_descendant_text():
    # Direct text only: "World" belongs to the nested <b>.
    result = run("-t", "//div[1]", stdin=MIXED)
    assert out(result) == "Hello !"


def test_text_flag_includes_text_after_a_child_element():
    # Every immediate text child is taken, not just the leading one -- see
    # AMBIGUITIES T11.
    result = run("-t", "//a", stdin=b"<r><a>x<b>y</b>z</a></r>")
    assert out(result) == "xz"


def test_text_flag_on_element_without_direct_text():
    # One line per element even when that line is empty -- see AMBIGUITIES T15.
    result = run("-t", "//a", stdin=b"<r><a><b>y</b></a></r>")
    assert result.returncode == 0
    assert out(result) == ""


# --- CLI: "... one per element." ------------------------------------------


def test_text_flag_emits_one_line_per_matched_element():
    doc = b"<r><a>one</a><a>two</a><a>three</a></r>"
    assert out(run("-t", "//a", stdin=doc)).splitlines() == ["one", "two", "three"]


def test_text_flag_joins_a_split_text_run_into_one_line():
    result = run("-t", "//a", stdin=b"<r><a>one <i>x</i>two</a><a>three</a></r>")
    assert out(result).splitlines() == ["one two", "three"]


# --- CLI: "`--text-all`: descendant text extraction ... one per element." --


def test_text_all_includes_descendant_text():
    result = run("--text-all", "//div[1]", stdin=MIXED)
    assert out(result) == "Hello World!"


def test_text_all_emits_one_line_per_matched_element():
    result = run("--text-all", "//div", stdin=MIXED)
    assert out(result).splitlines() == ["Hello World!", "plain"]


def test_text_all_works_with_css():
    result = run("--css", "--text-all", "div", stdin=MIXED)
    assert out(result).splitlines() == ["Hello World!", "plain"]


def test_text_all_descends_through_several_levels():
    doc = b"<r><a>1<b>2<c>3</c>4</b>5</a></r>"
    assert out(run("--text-all", "//a", stdin=doc)) == "12345"


# --- CSS: "`selector::text` returns direct text" --------------------------


def test_text_pseudo_element_returns_direct_text():
    result = run("--css", "Item::text", stdin=DOC)
    assert out(result) == "first\nsecond"


def test_text_pseudo_element_excludes_descendant_text():
    result = run("--css", "div::text", stdin=MIXED)
    assert out(result).splitlines() == ["Hello !", "plain"]


def test_text_pseudo_element_after_a_combinator():
    result = run("--css", "div b::text", stdin=MIXED)
    assert out(result) == "World"


def test_text_pseudo_element_exits_zero():
    assert run("--css", "Item::text", stdin=DOC).returncode == 0


# --- CSS: "`selector ::text` returns all descendant text nodes" -----------


def test_space_text_pseudo_element_returns_descendant_text_nodes():
    result = run("--css", "div ::text", stdin=b"<Root><div>Hello <b>World</b>!</div></Root>")
    assert out(result).splitlines() == ["Hello", "World", "!"]


def test_space_text_pseudo_element_reaches_nested_elements():
    doc = b"<r><a>1<b>2<c>3</c></b></a></r>"
    assert out(run("--css", "a ::text", stdin=doc)).splitlines() == ["1", "2", "3"]


# --- CSS: "... (one text node per line)." ---------------------------------


def test_each_descendant_text_node_gets_its_own_line():
    doc = b"<r><a>x<b>y</b>z</a></r>"
    assert out(run("--css", "a ::text", stdin=doc)).splitlines() == ["x", "y", "z"]


def test_descendant_mode_differs_from_text_all():
    # --text-all is one line per element, ` ::text` is one line per text node.
    doc = b"<r><a>x<b>y</b>z</a></r>"
    assert out(run("--css", "--text-all", "a", stdin=doc)) == "xyz"


def test_indentation_only_text_nodes_are_not_lines():
    # See AMBIGUITIES T19.
    doc = b"<r>\n  <ul>\n    <li>a</li>\n    <li>b</li>\n  </ul>\n</r>"
    assert out(run("--css", "ul ::text", stdin=doc)).splitlines() == ["a", "b"]


# --- CSS: "Comma-separated selectors are supported for `::text` queries" ---


def test_comma_separated_direct_text_selectors():
    doc = b"<r><a>one</a><b>two</b><c>three</c></r>"
    assert out(run("--css", "a::text, c::text", stdin=doc)).splitlines() == [
        "one",
        "three",
    ]


def test_comma_separated_descendant_text_selectors():
    doc = b"<r><a>one<i>x</i></a><b>two</b></r>"
    assert out(run("--css", "a ::text, b ::text", stdin=doc)).splitlines() == [
        "one",
        "x",
        "two",
    ]


def test_comma_separated_results_are_in_document_order():
    # See AMBIGUITIES T17.
    doc = b"<r><a>one</a><b>two</b></r>"
    assert out(run("--css", "b::text, a::text", stdin=doc)).splitlines() == [
        "one",
        "two",
    ]


def test_comma_separated_selectors_without_text_extraction():
    doc = b"<r><b>two</b><a>one</a></r>"
    assert out(run("--css", "a, b", stdin=doc)).rstrip("\n") == "<b>two</b>"


# --- CSS: "Mixing direct and descendant `::text` modes ... is invalid" ----


def test_mixed_text_modes_exit_one():
    assert run("--css", "a::text, b ::text", stdin=DOC).returncode == 1


def test_mixed_text_modes_write_to_stderr():
    result = run("--css", "a::text, b ::text", stdin=DOC)
    assert err(result).strip() != ""


def test_mixed_text_modes_write_nothing_to_stdout():
    result = run("--css", "a ::text, b::text", stdin=DOC)
    assert out(result) == ""


def test_text_mode_mixed_with_plain_selector_is_invalid():
    # A selector with no ::text is a third mode -- see AMBIGUITIES T13.
    result = run("--css", "Item::text, Root", stdin=DOC)
    assert result.returncode == 1
    assert err(result).strip() != ""


# --- CSS: "In CSS mode without text extraction, return XML node output" ---


def test_css_node_output_is_serialized_xml():
    result = run("--css", "Item", stdin=DOC)
    assert out(result).rstrip("\n").startswith("<Item")


def test_css_node_output_is_pretty_printed():
    doc = b"<root><parent><child a='1'>hi</child></parent></root>"
    result = run("--css", "parent", stdin=doc)
    assert out(result).rstrip("\n") == '<parent>\n  <child a="1">hi</child>\n</parent>'


def test_css_node_output_prints_only_the_first_match():
    # See AMBIGUITIES T12.
    result = run("--css", "Item", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="a" class="one">first</Item>'


# --- CSS: "Invalid CSS selector: stderr message, exit code `1`." ----------


@pytest.mark.parametrize("selector", ["div >", "a[", "::", "a::unknown", ""])
def test_invalid_css_selector_exits_one(selector):
    assert run("--css", selector, stdin=DOC).returncode == 1


def test_invalid_css_selector_writes_to_stderr():
    result = run("--css", "div >", stdin=DOC)
    assert err(result).strip() != ""


def test_invalid_css_selector_writes_nothing_to_stdout():
    result = run("--css", "div >", stdin=DOC)
    assert out(result) == ""


def test_invalid_css_message_references_css():
    result = run("--css", "div >", stdin=DOC)
    assert "css" in err(result).lower()


def test_text_pseudo_element_inside_a_selector_is_invalid():
    # ::text is a pseudo-element, so only a trailing one is meaningful -- see
    # AMBIGUITIES T18.
    result = run("--css", "a::text b", stdin=DOC)
    assert result.returncode == 1


def test_malformed_input_is_reported_before_the_selector():
    # Parsing still happens first -- see AMBIGUITIES T9.
    result = run("--css", "div >", stdin=b"<r><a></r>")
    assert result.returncode == 1
    message = err(result).lower()
    assert "xml" in message or "parse" in message


# --- Text Extraction: "Multi-match text output joins lines with `\n`." ----


def test_multiple_text_matches_are_newline_joined():
    doc = b"<r><a>one</a><a>two</a></r>"
    assert out(run("-t", "//a", stdin=doc)) == "one\ntwo"


def test_multiple_css_text_matches_are_newline_joined():
    assert out(run("--css", "Item::text", stdin=DOC)) == "first\nsecond"


def test_text_output_has_no_trailing_newline():
    assert not out(run("--css", "Item::text", stdin=DOC)).endswith("\n")


# --- Text Extraction: "Strip each result and collapse whitespace runs" ----


def test_extracted_text_is_stripped():
    result = run("-t", "//a", stdin=b"<r><a>   padded   </a></r>")
    assert out(result) == "padded"


def test_extracted_text_collapses_internal_runs():
    result = run("-t", "//a", stdin=b"<r><a>hello    world</a></r>")
    assert out(result) == "hello world"


def test_extracted_text_collapses_newlines_and_tabs():
    result = run("--css", "a::text", stdin=b"<r><a>\n hello \t\n world \n</a></r>")
    assert out(result) == "hello world"


def test_text_all_result_is_normalized():
    doc = b"<r><a>  one   <b>  two  </b>  </a></r>"
    assert out(run("--text-all", "//a", stdin=doc)) == "one two"


def test_descendant_text_nodes_are_each_normalized():
    doc = b"<r><a>  one   x <b>  two  </b></a></r>"
    assert out(run("--css", "a ::text", stdin=doc)).splitlines() == ["one x", "two"]


# --- Flag Rules: "If both `--text` and `--text-all`, `--text-all` wins." --


def test_text_all_wins_over_text():
    result = run("-t", "--text-all", "//div[1]", stdin=MIXED)
    assert out(result) == "Hello World!"


def test_text_all_wins_regardless_of_flag_order():
    result = run("--text-all", "--text", "//div[1]", stdin=MIXED)
    assert out(result) == "Hello World!"


def test_text_all_wins_in_css_mode():
    result = run("--css", "-t", "--text-all", "div", stdin=MIXED)
    assert out(result).splitlines() == ["Hello World!", "plain"]


# --- Flag Rules: "If query already extracts text ... no-op modifiers." ----


def test_text_flag_is_a_no_op_for_an_xpath_text_query():
    assert out(run("-t", "//Item/text()", stdin=DOC)) == "first\nsecond"


def test_text_all_flag_is_a_no_op_for_an_xpath_text_query():
    assert out(run("--text-all", "//div[1]/text()", stdin=MIXED)).splitlines() == [
        "Hello",
        "!",
    ]


def test_text_flag_is_a_no_op_for_a_direct_text_pseudo_query():
    result = run("--css", "-t", "div::text", stdin=MIXED)
    assert out(result).splitlines() == ["Hello !", "plain"]


def test_text_all_flag_is_a_no_op_for_a_direct_text_pseudo_query():
    # ::text already decided the mode, so --text-all must not widen it.
    result = run("--css", "--text-all", "div::text", stdin=MIXED)
    assert out(result).splitlines() == ["Hello !", "plain"]


def test_text_flag_is_a_no_op_for_a_descendant_text_pseudo_query():
    doc = b"<r><a>x<b>y</b>z</a></r>"
    result = run("--css", "-t", "a ::text", stdin=doc)
    assert out(result).splitlines() == ["x", "y", "z"]


def test_text_flag_is_a_no_op_for_attribute_results():
    # Nothing to extract from an attribute -- see AMBIGUITIES T14.
    assert out(run("-t", "//Item/@id", stdin=DOC)) == "a\nb"


def test_text_flag_is_a_no_op_for_scalar_results():
    assert out(run("-t", "count(//Item)", stdin=DOC)) == "2"


# --- Regression: behavior without the new flags is unchanged --------------


def test_plain_xpath_query_still_prints_first_node_only():
    assert out(run("//Item", stdin=DOC)).rstrip("\n") == (
        '<Item id="a" class="one">first</Item>'
    )


def test_plain_xpath_text_query_is_unchanged():
    assert out(run("//Item/text()", stdin=DOC)) == "first\nsecond"
