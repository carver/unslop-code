"""Spec tests for --json export and XPath unions, one section per phrase."""

import json
import subprocess
import sys
from pathlib import Path

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"

DOC = b"""<Root>
  <Item id="a">first</Item>
  <Item id="b">second</Item>
</Root>"""

UNION = b"""<Root>
  <Alpha>alpha</Alpha>
  <Beta>beta</Beta>
  <Gamma>gamma</Gamma>
</Root>"""

#: `Wrap` holds text of its own on both sides of a child element.
NESTED = b"<Root><Wrap>lead <Child>inner</Child> tail</Wrap><Note>note</Note></Root>"

ITEMS_JSON = """[
  {
    "Item": "first"
  },
  {
    "Item": "second"
  }
]"""

ITEMS_JSON_COMPACT = """[
{
"Item": "first"
},
{
"Item": "second"
}
]"""


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


# --- CLI: "`-j`, `--json`: JSON export mode for XML element results." -----


def test_short_json_flag_is_accepted():
    result = run("-j", "//Item", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == ITEMS_JSON


def test_long_json_flag_is_accepted():
    assert out(run("--json", "//Item", stdin=DOC)) == ITEMS_JSON


def test_json_output_parses_as_json():
    assert json.loads(out(run("-j", "//Item", stdin=DOC))) == [
        {"Item": "first"},
        {"Item": "second"},
    ]


def test_json_exports_element_results_rather_than_serializing_them():
    assert "<Item" not in out(run("-j", "//Item", stdin=DOC))


def test_json_flag_without_matches_stays_silent():
    # See AMBIGUITIES T41: an empty result prints nothing, not `[]`.
    assert out(run("-j", "//Missing", stdin=DOC)) == ""


# --- Precedence: "1. `--text-all` 2. `--text` 3. `--json` 4. default" -----


def test_text_all_wins_over_json():
    assert out(run("--text-all", "-j", "//Wrap", stdin=NESTED)) == "lead inner tail"


def test_text_wins_over_json():
    assert out(run("--text", "-j", "//Wrap", stdin=NESTED)) == "lead tail"


def test_text_all_wins_over_text_and_json_together():
    result = run("--text-all", "--text", "-j", "//Wrap", stdin=NESTED)
    assert out(result) == "lead inner tail"


def test_json_wins_over_the_default_element_format():
    assert out(run("-j", "//Item", stdin=DOC)) == ITEMS_JSON


def test_default_format_applies_without_any_output_flag():
    assert out(run("//Item", stdin=DOC)) == '<Item id="a">first</Item>'


# --- Precedence: "`--json` has no effect when results are already ---------
# --- auto-detected as text (e.g. text()/attribute outputs)." -------------


def test_json_has_no_effect_on_a_text_node_result():
    assert out(run("-j", "//Item/text()", stdin=DOC)) == "first\nsecond"


def test_json_has_no_effect_on_an_attribute_result():
    assert out(run("-j", "//Item/@id", stdin=DOC)) == "a\nb"


def test_json_has_no_effect_on_a_scalar_result():
    assert out(run("-j", "count(//Item)", stdin=DOC)) == "2"


def test_json_has_no_effect_on_a_string_function_result():
    assert out(run("-j", "string(//Item)", stdin=DOC)) == "first"


# --- Precedence: "In `--css` mode, `--json` has no effect and output ------
# --- follows the normal CSS rules for the query." ------------------------


def test_json_is_ignored_for_a_css_element_query():
    result = run("--css", "-j", "Item", stdin=DOC)
    assert out(result).rstrip("\n") == '<Item id="a">first</Item>'


def test_json_is_ignored_for_a_css_text_query():
    assert out(run("--css", "-j", "Item::text", stdin=DOC)) == "first\nsecond"


def test_json_is_ignored_for_a_css_query_under_compact():
    result = run("--css", "-j", "-c", "Item", stdin=DOC)
    assert out(result) == '<Item id="a">first</Item>'


# --- Contract: "Export shape: JSON array of objects ----------------------
# --- `{tag_name: immediate_text_content}`." ------------------------------


def test_export_is_a_json_array():
    assert isinstance(json.loads(out(run("-j", "//Item", stdin=DOC))), list)


def test_each_entry_is_an_object_keyed_by_the_tag_name():
    entries = json.loads(out(run("-j", "//Alpha | //Beta", stdin=UNION)))
    assert entries == [{"Alpha": "alpha"}, {"Beta": "beta"}]


def test_every_match_is_exported():
    assert len(json.loads(out(run("-j", "//Item", stdin=DOC)))) == 2


def test_element_without_text_exports_an_empty_string():
    doc = b"<Root><Item></Item></Root>"
    assert json.loads(out(run("-j", "//Item", stdin=doc))) == [{"Item": ""}]


def test_container_element_exports_an_empty_string():
    # See AMBIGUITIES T38: values are normalized, so source indentation is gone.
    assert json.loads(out(run("-j", "/Root", stdin=DOC))) == [{"Root": ""}]


# --- Contract: "Use immediate text only (exclude descendant text from -----
# --- child elements)." ---------------------------------------------------


def test_descendant_text_is_excluded():
    assert "inner" not in out(run("-j", "//Wrap", stdin=NESTED))


def test_text_on_both_sides_of_a_child_is_kept():
    # See AMBIGUITIES T37: every direct text node of the element, joined.
    assert json.loads(out(run("-j", "//Wrap", stdin=NESTED))) == [
        {"Wrap": "lead tail"}
    ]


def test_immediate_text_of_a_leaf_is_its_whole_text():
    assert json.loads(out(run("-j", "//Note", stdin=NESTED))) == [{"Note": "note"}]


# --- Contract: "Default JSON formatting: 2-space indent." ----------------


def test_default_json_uses_two_space_indent():
    assert out(run("-j", "//Item", stdin=DOC)) == ITEMS_JSON


def test_default_json_indents_keys_by_four_spaces_inside_an_object():
    assert '    "Item": "first"' in out(run("-j", "//Item", stdin=DOC))


def test_default_json_has_no_trailing_newline():
    assert not out(run("-j", "//Item", stdin=DOC)).endswith("\n")


# --- Contract: "With `--compact`, produce zero-indent JSON layout ---------
# --- (no leading whitespace)." -------------------------------------------


def test_compact_json_has_no_leading_whitespace_on_any_line():
    lines = out(run("-j", "-c", "//Item", stdin=DOC)).splitlines()
    assert lines and all(line == line.lstrip() for line in lines)


def test_compact_json_layout():
    # See AMBIGUITIES T39: zero indent still puts each token on its own line.
    assert out(run("-j", "--compact", "//Item", stdin=DOC)) == ITEMS_JSON_COMPACT


def test_compact_json_holds_the_same_data_as_the_default_layout():
    compact = json.loads(out(run("-j", "-c", "//Item", stdin=DOC)))
    assert compact == json.loads(out(run("-j", "//Item", stdin=DOC)))


# --- Contract: "With `--first`, still return a JSON array containing ------
# --- one exported element." ----------------------------------------------


def test_first_still_returns_an_array():
    assert json.loads(out(run("-j", "-f", "//Item", stdin=DOC))) == [{"Item": "first"}]


def test_first_exports_exactly_one_element():
    assert len(json.loads(out(run("-j", "--first", "//Item", stdin=DOC)))) == 1


def test_first_json_keeps_the_two_space_layout():
    expected = '[\n  {\n    "Item": "first"\n  }\n]'
    assert out(run("-j", "-f", "//Item", stdin=DOC)) == expected


def test_first_and_compact_json_layout():
    assert out(run("-j", "-f", "-c", "//Item", stdin=DOC)) == '[\n{\n"Item": "first"\n}\n]'


# --- Union: "Support XPath `|` union in XPath mode." ---------------------


def test_union_matches_both_sub_paths():
    entries = json.loads(out(run("-j", "//Alpha | //Gamma", stdin=UNION)))
    assert entries == [{"Alpha": "alpha"}, {"Gamma": "gamma"}]


def test_union_exits_zero():
    assert run("//Alpha | //Beta", stdin=UNION).returncode == 0


def test_union_of_text_paths_lists_each_result():
    assert out(run("//Alpha/text() | //Beta/text()", stdin=UNION)) == "alpha\nbeta"


def test_union_without_spaces_around_the_bar_is_the_same_query():
    assert out(run("//Alpha/text()|//Beta/text()", stdin=UNION)) == "alpha\nbeta"


def test_union_of_elements_defaults_to_serializing_the_first_match():
    assert out(run("//Beta | //Alpha", stdin=UNION)) == "<Alpha>alpha</Alpha>"


def test_union_result_is_in_document_order():
    entries = json.loads(out(run("-j", "//Gamma | //Alpha", stdin=UNION)))
    assert entries == [{"Alpha": "alpha"}, {"Gamma": "gamma"}]


def test_a_bar_inside_a_predicate_string_is_not_a_union():
    doc = b"<Root><Item id='a|b'>piped</Item></Root>"
    assert out(run("--text", "//Item[@id='a|b']", stdin=doc)) == "piped"


# --- Union: "`--text` and `--text-all` apply across union queries." ------


def test_text_applies_to_every_union_match():
    assert out(run("--text", "//Alpha | //Beta", stdin=UNION)) == "alpha\nbeta"


def test_text_across_a_union_keeps_one_result_per_match():
    # See AMBIGUITIES T43: only --text-all concatenates.
    assert out(run("-t", "//Wrap | //Note", stdin=NESTED)) == "lead tail\nnote"


def test_text_all_applies_to_every_union_match():
    assert "note" in out(run("--text-all", "//Wrap | //Note", stdin=NESTED))


# --- Union: "For XPath union queries with active `--text-all`, ------------
# --- concatenate descendant text across all union matches into one -------
# --- normalized output string." ------------------------------------------


def test_union_text_all_concatenates_into_one_string():
    # See AMBIGUITIES T42: matches are separated by a single space.
    assert out(run("--text-all", "//Wrap | //Note", stdin=NESTED)) == (
        "lead inner tail note"
    )


def test_union_text_all_output_is_a_single_line():
    assert "\n" not in out(run("--text-all", "//Alpha | //Beta", stdin=UNION))


def test_union_text_all_normalizes_whitespace():
    doc = b"<Root><A>  spaced\n  out  </A><B>\ttabbed\t</B></Root>"
    assert out(run("--text-all", "//A | //B", stdin=doc)) == "spaced out tabbed"


def test_union_text_all_over_three_matches():
    result = run("--text-all", "//Alpha | //Beta | //Gamma", stdin=UNION)
    assert out(result) == "alpha beta gamma"


def test_non_union_text_all_still_prints_one_line_per_match():
    assert out(run("--text-all", "//Item", stdin=DOC)) == "first\nsecond"


# --- Union: "If `--first` is also active with union + `--text-all`, ------
# --- only the first matched union node contributes to the output." -------


def test_first_limits_union_text_all_to_one_node():
    result = run("-f", "--text-all", "//Wrap | //Note", stdin=NESTED)
    assert out(result) == "lead inner tail"


def test_first_union_node_is_the_document_order_first():
    # See AMBIGUITIES T46: not the first match of the leftmost sub-path.
    result = run("--first", "--text-all", "//Note | //Wrap", stdin=NESTED)
    assert out(result) == "lead inner tail"


def test_first_union_text_all_drops_the_other_matches():
    assert "note" not in out(run("-f", "--text-all", "//Wrap | //Note", stdin=NESTED))


# --- Union: "If any union sub-path already performs text extraction, -----
# --- text flags are treated as no-op query modifiers." -------------------


def test_text_flag_is_a_no_op_when_a_sub_path_extracts_text():
    result = run("--text", "//Alpha/text() | //Beta/text()", stdin=UNION)
    assert out(result) == "alpha\nbeta"


def test_text_all_is_a_no_op_when_one_sub_path_extracts_text():
    # No concatenation: the flag modifies nothing, so the results stay separate.
    result = run("--text-all", "//Wrap/text() | //Note", stdin=NESTED)
    assert out(result) == "lead\ntail\nnote"


def test_text_all_is_a_no_op_when_a_sub_path_selects_an_attribute():
    result = run("--text-all", "//Item/@id | //Item", stdin=DOC)
    assert out(result) == "first\na\nsecond\nb"


def test_no_op_text_flag_still_exits_zero():
    result = run("--text", "//Alpha/text() | //Beta", stdin=UNION)
    assert result.returncode == 0


# --- Union: "A union with mixed result types is written as text results." -


def test_mixed_union_writes_elements_as_text():
    # See AMBIGUITIES T45: an element contributes its descendant text.
    result = run("//Wrap | //Note/text()", stdin=NESTED)
    assert out(result) == "lead inner tail\nnote"


def test_mixed_union_does_not_serialize_xml():
    assert "<Wrap>" not in out(run("//Wrap | //Note/text()", stdin=NESTED))


def test_mixed_union_joins_results_with_newlines():
    assert out(run("//Alpha | //Beta/text()", stdin=UNION)) == "alpha\nbeta"


def test_mixed_union_ignores_json_mode():
    assert out(run("-j", "//Alpha | //Beta/text()", stdin=UNION)) == "alpha\nbeta"


def test_mixed_union_honours_first():
    assert out(run("-f", "//Alpha | //Beta/text()", stdin=UNION)) == "alpha"


# --- Union: "In CSS mode, pass `|` through as CSS query text (no XPath ----
# --- union semantics). If the CSS engine rejects the selector, report a --
# --- CSS selector error on stderr with exit code `1`." -------------------


def test_css_union_selector_exits_one():
    assert run("--css", "Alpha | Beta", stdin=UNION).returncode == 1


def test_css_union_selector_reports_a_css_selector_error():
    message = err(run("--css", "Alpha | Beta", stdin=UNION)).lower()
    assert "css" in message or "selector" in message


def test_css_union_selector_writes_nothing_to_stdout():
    assert out(run("--css", "Alpha | Beta", stdin=UNION)) == ""


def test_css_bar_is_not_given_xpath_union_semantics():
    result = run("--css", "Alpha | Beta", stdin=UNION)
    assert "alpha" not in out(result)


def test_css_namespace_bar_is_a_selector_error():
    # See AMBIGUITIES T47: failures of a --css query are selector errors.
    result = run("--css", "Alpha|Beta", stdin=UNION)
    assert result.returncode == 1
    assert "css" in err(result).lower()


def test_css_union_error_is_unaffected_by_the_text_flags():
    assert run("--css", "--text", "Alpha | Beta", stdin=UNION).returncode == 1
