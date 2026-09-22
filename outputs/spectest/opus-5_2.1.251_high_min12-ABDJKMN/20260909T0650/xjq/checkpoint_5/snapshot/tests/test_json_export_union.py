"""Spec conformance tests for JSON export (`-j`/`--json`) and XPath unions.

Same convention as the other test modules: the spec is split into minimal
logical phrases and each section quotes its phrase (plus the minimal context it
needs) in a comment. Interpretation choices are cross-referenced as Tn ->
AMBIGUITIES.md.
"""

import json
import textwrap

import pytest

from conftest import run, run_argv

# ---------------------------------------------------------------------------
# Documents used across sections.
# ---------------------------------------------------------------------------

SIMPLE = "<root><item>a</item><item>b</item><item>c</item></root>"

# Direct text split around a child element: `one` is the element's own text and
# `three` is the child's tail, which is still text of `<div>` (T36).
SPLIT = '<root><div id="d">one<span>two</span>three</div></root>'

SPACED = "<root><div>one <span>two</span> three</div></root>"

PRETTY = textwrap.dedent(
    """\
    <root>
      <h1>Title</h1>
      <p>Hello <em>World</em></p>
      <aside>
        <b>x</b><i>y</i>
      </aside>
    </root>
    """
)


def parsed(result):
    """The stdout of a run, parsed back from JSON."""
    return json.loads(result.stdout)


# ===========================================================================
# Section E1
# Phrase: "`-j`, `--json`: JSON export mode for XML element results."
# Context: CLI Addition.
# ===========================================================================


def test_short_flag_j_is_accepted():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert r.returncode == 0
    assert r.stderr == ""


def test_long_flag_json_is_accepted():
    r = run_argv(["--json", "//item"], SIMPLE)
    assert r.returncode == 0
    assert r.stderr == ""


def test_short_and_long_json_agree():
    assert run_argv(["-j", "//item"], SIMPLE).stdout == (
        run_argv(["--json", "//item"], SIMPLE).stdout
    )


def test_json_flag_may_follow_the_query_argument():
    assert run_argv(["//item", "-j"], SIMPLE).stdout == (
        run_argv(["-j", "//item"], SIMPLE).stdout
    )


def test_json_mode_produces_json_for_element_results():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert parsed(r) == [{"item": "a"}, {"item": "b"}, {"item": "c"}]


def test_json_mode_replaces_the_xml_serialization():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert "<item>" not in r.stdout


# ===========================================================================
# Section E2
# Phrase: "When multiple output flags are present: 1. `--text-all`"
# Context: Output Precedence -- --text-all outranks --text and --json.
# ===========================================================================


def test_text_all_outranks_json():
    # Descendant text, one line per text node -- not a JSON export.
    r = run_argv(["--text-all", "-j", "//div"], SPLIT)
    assert r.lines == ["one", "two", "three"]


def test_text_all_outranks_json_regardless_of_flag_order():
    assert run_argv(["-j", "--text-all", "//div"], SPLIT).stdout == (
        run_argv(["--text-all", "-j", "//div"], SPLIT).stdout
    )


def test_text_all_outranks_text_and_json_together():
    # `--text-all` wins over both lower-ranked flags at once: descendant text,
    # not direct text, and not JSON.
    r = run_argv(["--text-all", "--text", "-j", "//div"], SPLIT)
    assert r.lines == ["one", "two", "three"]


# ===========================================================================
# Section E3
# Phrase: "When multiple output flags are present: ... 2. `--text`"
# Context: Output Precedence -- --text outranks --json.
# ===========================================================================


def test_text_outranks_json():
    r = run_argv(["--text", "-j", "//div"], SPLIT)
    assert r.lines == ["one", "three"]


def test_short_text_flag_outranks_json():
    r = run_argv(["-t", "-j", "//item"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


def test_text_and_json_output_is_not_json():
    r = run_argv(["-t", "-j", "//item"], SIMPLE)
    with pytest.raises(ValueError):
        json.loads(r.stdout)


# ===========================================================================
# Section E4
# Phrase: "When multiple output flags are present: ... 3. `--json`
#          4. default auto-format behavior"
# Context: Output Precedence.
# ===========================================================================


def test_json_outranks_the_default_node_format():
    # Default for element results is a single pretty-printed node (round 1);
    # with --json the export wins.
    assert run_argv(["//item"], SIMPLE).stdout.strip() == "<item>a</item>"
    assert parsed(run_argv(["-j", "//item"], SIMPLE)) == [
        {"item": "a"},
        {"item": "b"},
        {"item": "c"},
    ]


def test_default_behavior_without_json_flag_is_unchanged():
    r = run_argv(["//div"], SPLIT)
    assert r.stdout.startswith("<div")


def test_json_export_includes_every_match_not_only_the_first():
    # T35: --json replaces the "only the first node" default.
    assert len(parsed(run_argv(["-j", "//item"], SIMPLE))) == 3


# ===========================================================================
# Section E5
# Phrase: "`--json` has no effect when results are already auto-detected as
#          text (e.g., text()/attribute outputs)."
# Context: Output Precedence, notes.
# ===========================================================================


def test_json_has_no_effect_on_text_node_results():
    r = run_argv(["-j", "//item/text()"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


def test_json_has_no_effect_on_attribute_results():
    r = run_argv(["-j", "//div/@id"], SPLIT)
    assert r.lines == ["d"]


def test_json_has_no_effect_on_string_results():
    r = run_argv(["-j", "string(//item)"], SIMPLE)
    assert r.lines == ["a"]


def test_json_has_no_effect_on_numeric_results():
    r = run_argv(["-j", "count(//item)"], SIMPLE)
    assert r.lines == ["3"]


def test_json_has_no_effect_on_boolean_results():
    r = run_argv(["-j", "boolean(//item)"], SIMPLE)
    assert r.lines == ["true"]


def test_text_results_with_json_match_the_run_without_json():
    assert run_argv(["-j", "//item/text()"], SIMPLE).stdout == (
        run_argv(["//item/text()"], SIMPLE).stdout
    )


def test_json_with_no_matches_writes_nothing():
    # T38: the no-match rule comes first; no `[]` is emitted.
    r = run_argv(["-j", "//nope"], SIMPLE)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ===========================================================================
# Section E6
# Phrase: "In `--css` mode, `--json` has no effect and output follows the
#          normal CSS rules for the query."
# Context: Output Precedence, notes.
# ===========================================================================


def test_json_has_no_effect_in_css_mode():
    r = run_argv(["--css", "-j", "item"], SIMPLE)
    assert r.stdout.strip() == "<item>a</item>"


def test_css_node_output_with_json_matches_css_without_json():
    assert run_argv(["--css", "-j", "item"], SIMPLE).stdout == (
        run_argv(["--css", "item"], SIMPLE).stdout
    )


def test_css_text_pseudo_element_with_json_is_unchanged():
    r = run_argv(["--css", "-j", "div::text"], SPLIT)
    assert r.lines == ["one", "three"]


def test_css_mode_with_json_and_compact_still_follows_css_rules():
    r = run_argv(["--css", "-j", "-c", "item"], SIMPLE)
    assert r.stdout == "<item>a</item>\n"


def test_css_mode_with_json_and_first_still_follows_css_rules():
    r = run_argv(["--css", "-j", "-f", "item::text"], SIMPLE)
    assert r.lines == ["a"]


# ===========================================================================
# Section E7
# Phrase: "Export shape: JSON array of objects
#          `{tag_name: immediate_text_content}`."
# Context: JSON Export Contract.
# ===========================================================================


def test_export_is_a_json_array():
    assert isinstance(parsed(run_argv(["-j", "//item"], SIMPLE)), list)


def test_export_entries_are_objects():
    assert all(
        isinstance(entry, dict) for entry in parsed(run_argv(["-j", "//item"], SIMPLE))
    )


def test_export_object_key_is_the_tag_name():
    r = run_argv(["-j", "//div"], SPLIT)
    assert list(parsed(r)[0]) == ["div"]


def test_export_object_has_exactly_one_key():
    r = run_argv(["-j", "//div"], SPLIT)
    assert len(parsed(r)[0]) == 1


def test_export_value_is_the_text_content():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert [list(entry.values())[0] for entry in parsed(r)] == ["a", "b", "c"]


def test_export_keeps_document_order():
    assert parsed(run_argv(["-j", "//item"], SIMPLE)) == [
        {"item": "a"},
        {"item": "b"},
        {"item": "c"},
    ]


def test_export_does_not_include_attributes():
    r = run_argv(["-j", "//div"], SPLIT)
    assert "id" not in parsed(r)[0]


def test_export_of_a_single_match_is_still_an_array():
    assert parsed(run_argv(["-j", "//span"], SPLIT)) == [{"span": "two"}]


def test_export_of_json_converted_input_uses_json_keys_as_tags():
    r = run_argv(["-j", "//name"], '{"name": "Ada"}')
    assert parsed(r) == [{"name": "Ada"}]


def test_export_tag_names_keep_their_case():
    r = run_argv(["-j", "//Item"], "<Root><Item>up</Item></Root>")
    assert parsed(r) == [{"Item": "up"}]


# ===========================================================================
# Section E8
# Phrase: "Use immediate text only (exclude descendant text from child
#          elements)."
# Context: JSON Export Contract.
# ===========================================================================


def test_child_element_text_is_excluded():
    # T36: `two` lives in <span>, so it is not part of <div>'s immediate text.
    r = run_argv(["-j", "//div"], SPLIT)
    assert parsed(r) == [{"div": "onethree"}]


def test_immediate_text_includes_text_after_a_child_element():
    # A child's tail is text of the parent, not of the child (T36).
    assert parsed(run_argv(["-j", "//div"], SPLIT))[0]["div"].endswith("three")


def test_immediate_text_is_normalized():
    # Strip and collapse, as everywhere else in the tool (T36).
    r = run_argv(["-j", "//div"], SPACED)
    assert parsed(r) == [{"div": "one three"}]


def test_element_without_immediate_text_exports_empty_string():
    r = run_argv(["-j", "//aside"], PRETTY)
    assert parsed(r) == [{"aside": ""}]


def test_container_element_exports_no_descendant_text():
    r = run_argv(["-j", "/root"], SIMPLE)
    assert parsed(r) == [{"root": ""}]


def test_empty_element_exports_empty_string():
    r = run_argv(["-j", "//e"], "<root><e/></root>")
    assert parsed(r) == [{"e": ""}]


def test_leaf_elements_export_their_whole_text():
    r = run_argv(["-j", "//h1"], PRETTY)
    assert parsed(r) == [{"h1": "Title"}]


def test_immediate_text_of_a_mixed_leaf_and_container_set():
    r = run_argv(["-j", "//h1 | //p"], PRETTY)
    assert parsed(r) == [{"h1": "Title"}, {"p": "Hello"}]


# ===========================================================================
# Section E9
# Phrase: "Default JSON formatting: 2-space indent."
# Context: JSON Export Contract.
# ===========================================================================


def test_default_json_uses_two_space_indent():
    r = run_argv(["-j", "//item"], SIMPLE)
    expected = json.dumps([{"item": "a"}, {"item": "b"}, {"item": "c"}], indent=2)
    assert r.stdout == expected + "\n"


def test_default_json_indents_nested_keys_by_four_spaces():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert '\n    "item": "a"' in r.stdout


def test_default_json_is_multiline():
    assert run_argv(["-j", "//item"], SIMPLE).stdout.count("\n") > 1


def test_default_json_ends_with_a_newline():
    assert run_argv(["-j", "//item"], SIMPLE).stdout.endswith("]\n")


# ===========================================================================
# Section E10
# Phrase: "With `--compact`, produce zero-indent JSON layout (no leading
#          whitespace)."
# Context: JSON Export Contract.
# ===========================================================================


def test_compact_json_has_no_leading_whitespace_on_any_line():
    r = run_argv(["-j", "-c", "//item"], SIMPLE)
    assert all(line == line.lstrip() for line in r.stdout.splitlines())


def test_compact_json_is_the_zero_indent_layout():
    # T37: `indent=0` -- still one token per line, but nothing is indented.
    r = run_argv(["-j", "-c", "//item"], SIMPLE)
    expected = json.dumps([{"item": "a"}, {"item": "b"}, {"item": "c"}], indent=0)
    assert r.stdout == expected + "\n"


def test_compact_json_has_the_same_content_as_default_json():
    assert parsed(run_argv(["-j", "-c", "//item"], SIMPLE)) == (
        parsed(run_argv(["-j", "//item"], SIMPLE))
    )


def test_long_compact_flag_behaves_like_short():
    assert run_argv(["-j", "--compact", "//item"], SIMPLE).stdout == (
        run_argv(["-j", "-c", "//item"], SIMPLE).stdout
    )


def test_compact_json_differs_from_default_json():
    assert run_argv(["-j", "-c", "//item"], SIMPLE).stdout != (
        run_argv(["-j", "//item"], SIMPLE).stdout
    )


# ===========================================================================
# Section E11
# Phrase: "With `--first`, still return a JSON array containing one exported
#          element."
# Context: JSON Export Contract.
# ===========================================================================


def test_json_with_first_is_still_an_array():
    assert isinstance(parsed(run_argv(["-j", "-f", "//item"], SIMPLE)), list)


def test_json_with_first_holds_exactly_one_element():
    assert parsed(run_argv(["-j", "-f", "//item"], SIMPLE)) == [{"item": "a"}]


def test_json_with_long_first_flag():
    assert parsed(run_argv(["-j", "--first", "//item"], SIMPLE)) == [{"item": "a"}]


def test_json_first_element_is_the_first_in_document_order():
    r = run_argv(["-j", "-f", "//h1 | //p"], PRETTY)
    assert parsed(r) == [{"h1": "Title"}]


def test_json_first_and_compact_combine():
    r = run_argv(["-j", "-f", "-c", "//item"], SIMPLE)
    assert r.stdout == json.dumps([{"item": "a"}], indent=0) + "\n"


def test_json_first_with_no_matches_writes_nothing():
    r = run_argv(["-j", "-f", "//nope"], SIMPLE)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ===========================================================================
# Section E12
# Phrase: "Support XPath `|` union in XPath mode."
# Context: XPath Union.
# ===========================================================================


def test_union_query_is_accepted():
    r = run_argv(["//h1 | //p"], PRETTY)
    assert r.returncode == 0
    assert r.stderr == ""


def test_union_matches_both_sub_paths():
    r = run_argv(["-j", "//h1 | //p"], PRETTY)
    assert [list(entry)[0] for entry in parsed(r)] == ["h1", "p"]


def test_union_results_are_in_document_order():
    r = run_argv(["-j", "//p | //h1"], PRETTY)
    assert [list(entry)[0] for entry in parsed(r)] == ["h1", "p"]


def test_union_default_node_output_prints_the_first_node():
    r = run_argv(["//h1 | //p"], PRETTY)
    assert r.stdout.strip() == "<h1>Title</h1>"


def test_union_without_spaces_around_the_bar():
    assert run_argv(["-j", "//h1|//p"], PRETTY).stdout == (
        run_argv(["-j", "//h1 | //p"], PRETTY).stdout
    )


def test_union_with_three_sub_paths():
    r = run_argv(["-j", "//h1 | //p | //aside"], PRETTY)
    assert [list(entry)[0] for entry in parsed(r)] == ["h1", "p", "aside"]


def test_union_deduplicates_nodes_matched_twice():
    r = run_argv(["-j", "//h1 | //h1"], PRETTY)
    assert parsed(r) == [{"h1": "Title"}]


def test_union_where_one_sub_path_matches_nothing():
    r = run_argv(["-j", "//h1 | //nope"], PRETTY)
    assert parsed(r) == [{"h1": "Title"}]


def test_union_where_no_sub_path_matches_is_silent():
    r = run_argv(["//nope | //neither"], PRETTY)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_union_of_attribute_paths():
    r = run_argv(["//div/@id | //span/@id"], SPLIT)
    assert r.lines == ["d"]


def test_union_on_json_converted_input():
    doc = '{"a": "one", "b": "two"}'
    r = run_argv(["-j", "//a | //b"], doc)
    assert parsed(r) == [{"a": "one"}, {"b": "two"}]


# ===========================================================================
# Section E13
# Phrase: "`--text` and `--text-all` apply across union queries."
# Context: XPath Union.
# ===========================================================================


def test_text_flag_applies_to_every_union_match():
    # T46: only --text-all concatenates; --text keeps one line per text node.
    r = run_argv(["-t", "//h1 | //p"], PRETTY)
    assert r.lines == ["Title", "Hello"]


def test_text_flag_across_union_covers_both_sub_paths():
    r = run_argv(["-t", "//h1 | //em"], PRETTY)
    assert r.lines == ["Title", "World"]


def test_text_all_applies_across_union_matches():
    r = run_argv(["--text-all", "//h1 | //em"], PRETTY)
    assert r.lines == ["TitleWorld"]


def test_text_flag_with_first_on_a_union_keeps_the_first_line():
    r = run_argv(["-t", "-f", "//h1 | //p"], PRETTY)
    assert r.lines == ["Title"]


def test_text_flag_on_a_union_where_one_sub_path_misses():
    r = run_argv(["-t", "//h1 | //nope"], PRETTY)
    assert r.lines == ["Title"]


# ===========================================================================
# Section E14
# Phrase: "For XPath union queries with active `--text-all`, concatenate
#          descendant text across all union matches into one normalized output
#          string."
# Context: XPath Union.
# ===========================================================================


def test_union_text_all_is_a_single_line():
    r = run_argv(["--text-all", "//h1 | //p"], PRETTY)
    assert len(r.lines) == 1


def test_union_text_all_concatenates_descendant_text():
    # T41: concatenation, then normalization of the whole string.
    r = run_argv(["--text-all", "//h1 | //p"], PRETTY)
    assert r.lines == ["TitleHello World"]


def test_union_text_all_includes_nested_element_text():
    # A union with one dead sub-path is still a union, so the whole subtree of
    # <aside> collapses into one string.
    r = run_argv(["--text-all", "//aside | //nope"], PRETTY)
    assert r.lines == ["xy"]


def test_union_text_all_across_three_sub_paths():
    # The whitespace inside <aside> is part of the concatenation and collapses
    # to a single space during normalization.
    r = run_argv(["--text-all", "//h1 | //p | //aside"], PRETTY)
    assert r.lines == ["TitleHello World xy"]


def test_union_text_all_output_is_normalized():
    doc = "<root><a>  spaced   out  </a><b>\n\tmore\n</b></root>"
    r = run_argv(["--text-all", "//a | //b"], doc)
    assert r.lines == ["spaced out more"]


def test_non_union_text_all_still_prints_one_line_per_text_node():
    # The concatenation rule is scoped to unions (T40).
    r = run_argv(["--text-all", "//p"], PRETTY)
    assert r.lines == ["Hello", "World"]


def test_union_text_all_with_no_matches_is_silent():
    r = run_argv(["--text-all", "//nope | //neither"], PRETTY)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_union_text_all_ends_with_a_newline():
    assert run_argv(["--text-all", "//h1 | //p"], PRETTY).stdout.endswith("\n")


def test_union_text_all_outranks_json():
    r = run_argv(["--text-all", "-j", "//h1 | //p"], PRETTY)
    assert r.lines == ["TitleHello World"]


# ===========================================================================
# Section E15
# Phrase: "If `--first` is also active with union + `--text-all`, only the
#          first matched union node contributes to the output."
# Context: XPath Union.
# ===========================================================================


def test_union_text_all_with_first_uses_only_the_first_node():
    r = run_argv(["--text-all", "-f", "//h1 | //p"], PRETTY)
    assert r.lines == ["Title"]


def test_union_text_all_with_first_keeps_all_of_that_nodes_text():
    # The whole first node contributes, not just its first text node.
    r = run_argv(["--text-all", "-f", "//p | //aside"], PRETTY)
    assert r.lines == ["Hello World"]


def test_union_text_all_first_node_is_document_order_not_query_order():
    # T43: `//p | //h1` still starts at <h1>.
    r = run_argv(["--text-all", "-f", "//p | //h1"], PRETTY)
    assert r.lines == ["Title"]


def test_union_text_all_with_short_first_flag():
    assert run_argv(["--text-all", "--first", "//h1 | //p"], PRETTY).stdout == (
        run_argv(["--text-all", "-f", "//h1 | //p"], PRETTY).stdout
    )


def test_union_text_all_with_first_is_still_one_line():
    r = run_argv(["--text-all", "-f", "//h1 | //aside"], PRETTY)
    assert len(r.lines) == 1


def test_union_text_all_with_first_and_no_matches_is_silent():
    r = run_argv(["--text-all", "-f", "//nope | //neither"], PRETTY)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ===========================================================================
# Section E16
# Phrase: "If any union sub-path already performs text extraction, text flags
#          are treated as no-op query modifiers."
# Context: XPath Union.
# ===========================================================================


def test_text_all_is_a_no_op_when_a_sub_path_extracts_text():
    # T42: the query already says text(), so --text-all changes nothing; the
    # results are the raw union (a text node and an element).
    r = run_argv(["--text-all", "//h1/text() | //em"], PRETTY)
    assert r.lines == ["Title", "World"]


def test_text_flag_is_a_no_op_when_a_sub_path_extracts_text():
    r = run_argv(["-t", "//h1/text() | //em"], PRETTY)
    assert r.lines == ["Title", "World"]


def test_no_op_text_flags_do_not_concatenate():
    # Without the no-op rule this would be one concatenated line.
    r = run_argv(["--text-all", "//h1/text() | //p"], PRETTY)
    assert len(r.lines) > 1


def test_no_op_text_flag_matches_the_run_without_the_flag():
    assert run_argv(["--text-all", "//h1/text() | //em/text()"], PRETTY).stdout == (
        run_argv(["//h1/text() | //em/text()"], PRETTY).stdout
    )


def test_no_op_applies_when_the_second_sub_path_extracts_text():
    assert run_argv(["-t", "//em | //h1/text()"], PRETTY).stdout == (
        run_argv(["//em | //h1/text()"], PRETTY).stdout
    )


def test_all_sub_paths_extracting_text_is_also_a_no_op():
    r = run_argv(["--text-all", "//h1/text() | //em/text()"], PRETTY)
    assert r.lines == ["Title", "World"]


def test_no_op_text_flags_still_honor_first():
    r = run_argv(["--text-all", "-f", "//h1/text() | //em/text()"], PRETTY)
    assert r.lines == ["Title"]


def test_no_op_text_flag_leaves_json_inert():
    # T44: precedence is decided by which flags are present, so a neutralized
    # --text-all still keeps --json from taking over.
    assert run_argv(["--text-all", "-j", "//h1/text() | //em"], PRETTY).stdout == (
        run_argv(["--text-all", "//h1/text() | //em"], PRETTY).stdout
    )


def test_text_extraction_in_a_string_literal_is_not_a_sub_path_extraction():
    # T40/T42: `text()` here is data inside a literal, not a node test.
    doc = '<root><a t="text()">A</a><b>B</b></root>'
    r = run_argv(["--text-all", '//a[@t="text()"] | //b'], doc)
    assert r.lines == ["AB"]


def test_non_union_query_with_text_extraction_is_unaffected():
    # Round 1 already made the flags no-ops for text results.
    r = run_argv(["--text-all", "//h1/text()"], PRETTY)
    assert r.lines == ["Title"]


# ===========================================================================
# Section E17
# Phrase: "In CSS mode, pass `|` through as CSS query text (no XPath union
#          semantics). If the CSS engine rejects the selector, report a CSS
#          selector error on stderr with exit code `1`."
# Context: XPath Union.
# ===========================================================================


def test_css_union_selector_exits_one():
    assert run_argv(["--css", "h1 | p"], PRETTY).returncode == 1


def test_css_union_selector_writes_to_stderr():
    assert run_argv(["--css", "h1 | p"], PRETTY).stderr.strip() != ""


def test_css_union_selector_writes_nothing_to_stdout():
    assert run_argv(["--css", "h1 | p"], PRETTY).stdout == ""


def test_css_union_error_message_mentions_css_or_selector():
    low = run_argv(["--css", "h1 | p"], PRETTY).stderr.lower()
    assert "css" in low or "selector" in low


def test_css_bar_has_no_union_semantics():
    # It must not behave like the XPath union, which would match both.
    r = run_argv(["--css", "h1 | p"], PRETTY)
    assert "Title" not in r.stdout


def test_css_namespace_bar_without_spaces_is_also_a_selector_error():
    # `h1|p` parses as the namespaced selector `p` in namespace `h1`, which no
    # engine can resolve here (T45).
    r = run_argv(["--css", "h1|p"], PRETTY)
    assert r.returncode == 1
    low = r.stderr.lower()
    assert "css" in low or "selector" in low


def test_css_namespace_wildcard_selector_is_honored():
    # `*|h1` is a valid CSS selector (any namespace) and is not a union.
    r = run_argv(["--css", "*|h1"], PRETTY)
    assert r.returncode == 0
    assert r.stdout.strip() == "<h1>Title</h1>"


def test_css_comma_is_still_the_css_selector_list():
    r = run_argv(["--css", "h1, p"], PRETTY)
    assert r.returncode == 0
    assert r.stdout.strip() == "<h1>Title</h1>"


def test_css_union_with_json_is_still_a_selector_error():
    assert run_argv(["--css", "-j", "h1 | p"], PRETTY).returncode == 1


def test_xpath_union_is_unaffected_by_the_css_rule():
    assert run_argv(["//h1 | //p"], PRETTY).returncode == 0


# ===========================================================================
# Section E18 -- interactions between phrases (integration)
# ===========================================================================


def test_integration_json_first_compact_on_a_union():
    r = run_argv(["-j", "-f", "-c", "//h1 | //p"], PRETTY)
    assert r.stdout == json.dumps([{"h1": "Title"}], indent=0) + "\n"


def test_integration_bundled_short_flags():
    r = run_argv(["-jfc", "//item"], SIMPLE)
    assert r.stdout == json.dumps([{"item": "a"}], indent=0) + "\n"


def test_integration_json_from_a_file(tmp_path):
    path = tmp_path / "doc.xml"
    path.write_text(SIMPLE, encoding="utf-8")
    r = run_argv(["-j", "//item", str(path)])
    assert parsed(r) == [{"item": "a"}, {"item": "b"}, {"item": "c"}]


def test_integration_union_text_all_from_a_file(tmp_path):
    path = tmp_path / "doc.xml"
    path.write_text(PRETTY, encoding="utf-8")
    r = run_argv(["--text-all", "//h1 | //p", str(path)])
    assert r.lines == ["TitleHello World"]


def test_integration_json_export_of_json_input_array():
    r = run_argv(["-j", "//item"], '["x", "y"]')
    assert parsed(r) == [{"item": "x"}, {"item": "y"}]


def test_integration_invalid_union_xpath_is_an_error():
    r = run_argv(["//h1 |"], PRETTY)
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr.strip() != ""


def test_integration_json_does_not_change_the_exit_code():
    assert run_argv(["-j", "//item"], SIMPLE).returncode == 0


def test_integration_json_export_is_reparseable_round_trip():
    r = run_argv(["-j", "//item"], SIMPLE)
    assert json.loads(r.stdout) == json.loads(
        run_argv(["-j", "-c", "//item"], SIMPLE).stdout
    )


def test_integration_json_mode_with_malformed_input_still_errors():
    r = run_argv(["-j", "//item"], "<root><item>a</root>")
    assert r.returncode == 1
    assert r.stdout == ""
