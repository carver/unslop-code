"""Spec section: Smart Output Formatting / JSON Export.

Covers the `-j`/`--json` CLI addition, the output-precedence list, and the
JSON export contract.  Each test section quotes the minimal spec phrase it
covers.
"""
import json

import pytest


# --- Phrase: "`-j`, `--json`: JSON export mode for XML element results." ---
# Context: a new flag, both spellings, turning element results into JSON.

def test_json_long_flag_is_accepted(xjq, books):
    r = xjq("--json", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stderr == ""


def test_json_short_flag_is_accepted(xjq, books):
    r = xjq("-j", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stderr == ""


def test_short_and_long_json_flags_agree(xjq, books):
    short = xjq("-j", "//title", stdin=books)
    long = xjq("--json", "//title", stdin=books)
    assert short.stdout == long.stdout


def test_json_mode_output_is_valid_json(xjq, books):
    r = xjq("-j", "//title", stdin=books)
    assert r.returncode == 0
    json.loads(r.stdout)


def test_json_mode_replaces_xml_node_output(xjq, books):
    r = xjq("-j", "//title", stdin=books)
    assert r.returncode == 0
    assert "<title>" not in r.stdout


def test_json_mode_exports_every_matched_element(xjq, books):
    # The default XML branch prints only the first node; JSON export covers
    # the whole element result set.
    r = xjq("-j", "//title", stdin=books)
    assert json.loads(r.stdout) == [
        {"title": "Dune"},
        {"title": "Le Petit Prince"},
        {"title": "Neuromancer"},
    ]


def test_json_mode_with_no_match_writes_nothing(xjq, books):
    r = xjq("-j", "//nosuch", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


# --- Phrase: "Output Precedence ... 1. `--text-all` 2. `--text` 3. `--json`
#             4. default auto-format behavior" --------------------------
# Context: several output flags given at once; the first present wins.

def test_text_all_beats_text_and_json(xjq, mixed):
    r = xjq("--text-all", "--text", "-j", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello bold world"


def test_text_all_beats_json(xjq, mixed):
    r = xjq("--text-all", "-j", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello bold world"


def test_text_beats_json(xjq, mixed):
    r = xjq("--text", "-j", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "Hello world"


def test_json_beats_default_auto_format(xjq, mixed):
    r = xjq("-j", "//p", stdin=mixed)
    assert r.returncode == 0
    assert json.loads(r.stdout) == [{"p": "Hello world"}]


def test_default_auto_format_applies_without_flags(xjq, mixed):
    r = xjq("//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout.startswith("<p>")


def test_flag_order_on_the_command_line_does_not_matter(xjq, mixed):
    a = xjq("-j", "--text", "//p", stdin=mixed)
    b = xjq("--text", "-j", "//p", stdin=mixed)
    assert a.stdout == b.stdout == "Hello world"


def test_text_all_precedence_holds_for_multiple_elements(xjq, books):
    r = xjq("--text-all", "-j", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


# --- Phrase: "`--json` has no effect when results are already
#             auto-detected as text (e.g. text()/attribute outputs)." -----
# Context: the query itself yields text, so JSON export is skipped.

def test_json_has_no_effect_on_text_node_results(xjq, books):
    r = xjq("-j", "//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


def test_json_has_no_effect_on_attribute_results(xjq, books):
    r = xjq("-j", "//book/@id", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["b1", "b2", "b3"]


def test_json_has_no_effect_on_string_function_results(xjq, books):
    r = xjq("-j", "string(//title)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_json_has_no_effect_on_numeric_results(xjq, books):
    r = xjq("-j", "count(//book)", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "3"


def test_json_has_no_effect_on_boolean_results(xjq, books):
    r = xjq("-j", "count(//book) > 1", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "true"


def test_text_result_under_json_is_not_wrapped_in_an_array(xjq, books):
    r = xjq("-j", "//title/text()", stdin=books)
    assert not r.stdout.startswith("[")


# --- Phrase: "In `--css` mode, `--json` has no effect and output follows
#             the normal CSS rules for the query." ------------------------
# Context: --css wins over JSON export entirely.

def test_json_has_no_effect_in_css_mode(xjq, books):
    plain = xjq("--css", "title", stdin=books)
    with_json = xjq("--css", "-j", "title", stdin=books)
    assert with_json.returncode == 0
    assert with_json.stdout == plain.stdout


def test_css_node_output_stays_xml_under_json(xjq, books):
    r = xjq("--css", "-j", "title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_css_text_pseudo_still_wins_under_json(xjq, books):
    r = xjq("--css", "-j", "title::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


def test_css_mode_with_json_and_first(xjq, books):
    r = xjq("--css", "-j", "-f", "title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_invalid_css_selector_under_json_still_errors(xjq, books):
    r = xjq("--css", "-j", "div >", stdin=books)
    assert r.returncode == 1
    assert r.stdout == ""


# --- Phrase: "Export shape: JSON array of objects
#             `{tag_name: immediate_text_content}`." ---------------------
# Context: one single-key object per exported element.

def test_export_is_a_json_array(xjq, books):
    r = xjq("-j", "//title", stdin=books)
    assert isinstance(json.loads(r.stdout), list)


def test_each_entry_is_an_object(xjq, books):
    data = json.loads(xjq("-j", "//title", stdin=books).stdout)
    assert all(isinstance(entry, dict) for entry in data)


def test_each_object_has_exactly_one_key(xjq, books):
    data = json.loads(xjq("-j", "//book/*", stdin=books).stdout)
    assert all(len(entry) == 1 for entry in data)


def test_object_key_is_the_tag_name(xjq, books):
    data = json.loads(xjq("-j", "//book/*", stdin=books).stdout)
    assert [k for entry in data for k in entry][:3] == ["title", "author", "year"]


def test_object_value_is_the_element_text(xjq, books):
    data = json.loads(xjq("-j", "//author", stdin=books).stdout)
    assert data == [
        {"author": "Frank Herbert"},
        {"author": "Antoine de Saint-Exupery"},
        {"author": "William Gibson"},
    ]


def test_export_keeps_document_order(xjq, books):
    data = json.loads(xjq("-j", "//year", stdin=books).stdout)
    assert [v for entry in data for v in entry.values()] == ["1965", "1943", "1984"]


def test_repeated_tag_names_each_get_their_own_object(xjq, books):
    data = json.loads(xjq("-j", "//title", stdin=books).stdout)
    assert len(data) == 3


def test_single_match_is_still_an_array(xjq, books):
    data = json.loads(xjq("-j", "//book[1]/title", stdin=books).stdout)
    assert data == [{"title": "Dune"}]


def test_export_of_converted_json_input(xjq):
    data = json.loads(xjq("-j", "/root/a", stdin='{"a": "x"}').stdout)
    assert data == [{"a": "x"}]


# --- Phrase: "Use immediate text only (exclude descendant text from child
#             elements)." -------------------------------------------------
# Context: the same direct-text rule as `--text`, not `--text-all`.

def test_immediate_text_excludes_child_element_text(xjq, mixed):
    data = json.loads(xjq("-j", "//p", stdin=mixed).stdout)
    assert data == [{"p": "Hello world"}]


def test_immediate_text_does_not_contain_descendant_words(xjq, mixed):
    r = xjq("-j", "//p", stdin=mixed)
    assert "bold" not in r.stdout


def test_container_element_with_only_child_elements_exports_empty_text(xjq, books):
    data = json.loads(xjq("-j", "//book", stdin=books).stdout)
    assert data == [{"book": ""}, {"book": ""}, {"book": ""}]


def test_immediate_text_matches_the_text_flag(xjq, mixed):
    data = json.loads(xjq("-j", "//p", stdin=mixed).stdout)
    text_flag = xjq("--text", "//p", stdin=mixed).stdout
    assert list(data[0].values()) == [text_flag]


def test_immediate_text_includes_tail_text_of_children(xjq):
    doc = "<doc><p>before <b>skip</b> after</p></doc>"
    data = json.loads(xjq("-j", "//p", stdin=doc).stdout)
    assert data == [{"p": "before after"}]


def test_immediate_text_is_whitespace_normalized(xjq):
    doc = "<doc><p>\n   spaced   out\n  </p></doc>"
    data = json.loads(xjq("-j", "//p", stdin=doc).stdout)
    assert data == [{"p": "spaced out"}]


def test_empty_element_exports_empty_string(xjq):
    doc = "<doc><a></a></doc>"
    data = json.loads(xjq("-j", "//a", stdin=doc).stdout)
    assert data == [{"a": ""}]


def test_export_value_is_always_a_string(xjq, books):
    data = json.loads(xjq("-j", "//year", stdin=books).stdout)
    assert all(isinstance(v, str) for entry in data for v in entry.values())


# --- Phrase: "Default JSON formatting: 2-space indent." ------------------
# Context: no --compact, so the array is pretty-printed with two spaces.

def test_default_indent_is_two_spaces(xjq, books):
    r = xjq("-j", "//book[1]/title", stdin=books)
    assert r.stdout == '[\n  {\n    "title": "Dune"\n  }\n]'


def test_default_indent_nesting_levels(xjq, books):
    lines = xjq("-j", "//book[1]/title", stdin=books).stdout.splitlines()
    assert lines[0] == "["
    assert lines[1] == "  {"
    assert lines[2] == '    "title": "Dune"'
    assert lines[3] == "  }"
    assert lines[4] == "]"


def test_default_indent_for_multiple_entries(xjq, books):
    lines = xjq("-j", "//title", stdin=books).stdout.splitlines()
    assert lines.count("  {") == 3
    assert lines.count("  },") == 2
    assert lines.count("  }") == 1


def test_default_output_has_no_trailing_newline(xjq, books):
    r = xjq("-j", "//title", stdin=books)
    assert not r.stdout.endswith("\n")


# --- Phrase: "With `--compact`, produce zero-indent JSON layout
#             (no leading whitespace)." ---------------------------------
# Context: --compact removes the indentation from the JSON layout.

def test_compact_json_has_no_leading_whitespace(xjq, books):
    r = xjq("-j", "-c", "//title", stdin=books)
    assert r.returncode == 0
    assert all(line == line.lstrip() for line in r.stdout.splitlines())


def test_compact_json_layout(xjq, books):
    r = xjq("-j", "--compact", "//book[1]/title", stdin=books)
    assert r.stdout == '[\n{\n"title": "Dune"\n}\n]'


def test_compact_json_is_still_valid_json(xjq, books):
    r = xjq("-j", "-c", "//title", stdin=books)
    assert json.loads(r.stdout) == [
        {"title": "Dune"},
        {"title": "Le Petit Prince"},
        {"title": "Neuromancer"},
    ]


def test_compact_and_default_carry_the_same_data(xjq, books):
    compact = json.loads(xjq("-j", "-c", "//book/*", stdin=books).stdout)
    default = json.loads(xjq("-j", "//book/*", stdin=books).stdout)
    assert compact == default


def test_compact_json_has_no_trailing_newline(xjq, books):
    r = xjq("-j", "-c", "//title", stdin=books)
    assert not r.stdout.endswith("\n")


def test_compact_only_affects_json_layout_not_content(xjq, mixed):
    data = json.loads(xjq("-j", "-c", "//p", stdin=mixed).stdout)
    assert data == [{"p": "Hello world"}]


# --- Phrase: "With `--first`, still return a JSON array containing one
#             exported element." -----------------------------------------
# Context: --first truncates the export to one entry but keeps the array.

def test_first_exports_a_one_entry_array(xjq, books):
    data = json.loads(xjq("-j", "-f", "//title", stdin=books).stdout)
    assert data == [{"title": "Dune"}]


def test_first_long_flag_exports_a_one_entry_array(xjq, books):
    data = json.loads(xjq("--json", "--first", "//title", stdin=books).stdout)
    assert data == [{"title": "Dune"}]


def test_first_json_output_is_still_a_list(xjq, books):
    r = xjq("-j", "-f", "//title", stdin=books)
    assert r.stdout.startswith("[")
    assert r.stdout.endswith("]")


def test_first_keeps_the_two_space_indent(xjq, books):
    r = xjq("-j", "-f", "//title", stdin=books)
    assert r.stdout == '[\n  {\n    "title": "Dune"\n  }\n]'


def test_first_with_compact_json(xjq, books):
    r = xjq("-j", "-f", "-c", "//title", stdin=books)
    assert r.stdout == '[\n{\n"title": "Dune"\n}\n]'


def test_first_on_a_single_match_is_unchanged(xjq, books):
    with_first = xjq("-j", "-f", "//book[1]/title", stdin=books)
    without = xjq("-j", "//book[1]/title", stdin=books)
    assert with_first.stdout == without.stdout


def test_first_with_no_match_writes_nothing(xjq, books):
    r = xjq("-j", "-f", "//nosuch", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""
