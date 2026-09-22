"""Spec conformance tests for JSON input auto-detection and JSON->XML conversion.

Each section quotes one minimal spec phrase (plus the minimal context needed to
read it) and tests only that phrase. Interpretation choices are cross-referenced
as Tn -> AMBIGUITIES.md.

The converted document is observed through xjq's own query surface: `/*`
serializes the whole converted tree, and targeted XPath expressions read
individual tags, attributes and text.
"""

import json

import pytest

from conftest import run


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def tree(stdin):
    """The whole converted document, pretty-printed by xjq's node renderer."""
    r = run("/*", stdin)
    assert r.returncode == 0, r.stderr
    return r.stdout


def value(query, stdin):
    """A single string-valued XPath result, without the trailing newline."""
    r = run(query, stdin)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


XML_DOC = "<root><item>a</item><item>b</item></root>"


# ===========================================================================
# Section J1
# Phrase: "Auto-detect stdin as JSON object/array or XML/HTML."
# Context: Input Auto-Detection -- no flag selects the mode.
# ===========================================================================


def test_top_level_json_object_is_detected_as_json():
    # No flag: a JSON object on stdin is converted and queryable as XML.
    assert value("string(/root/a)", '{"a": "x"}') == "x"


def test_top_level_json_array_is_detected_as_json():
    assert run("//item/text()", "[1, 2, 3]").lines == ["1", "2", "3"]


def test_xml_input_still_parses_as_xml():
    # Detection must not disturb ordinary XML documents.
    assert run("//item/text()", XML_DOC).lines == ["a", "b"]


def test_json_detection_ignores_surrounding_whitespace():
    assert value("string(/root/a)", '\n\t  {"a": "x"}  \n') == "x"


def test_detection_needs_no_flag_and_query_applies_to_converted_tree():
    # The query is evaluated against the converted document, not the raw text.
    assert value("count(/root/*)", '{"a": 1, "b": 2}') == "2"


# ===========================================================================
# Section J2
# Phrase: "Top-level JSON primitives are not accepted as JSON input for this
#          mode; they fall back to XML parsing."
# Context: a valid JSON string/number/bool/null document is *not* JSON here.
# ===========================================================================


@pytest.mark.parametrize(
    "primitive",
    ['"hello"', "123", "1.5", "true", "false", "null", '  "hello"  '],
)
def test_top_level_primitive_is_not_json_input(primitive):
    # It falls back to XML parsing, where it is not well formed: exit 1 (T1).
    r = run("//*", primitive)
    assert r.returncode == 1
    assert r.stderr.strip()


def test_top_level_primitive_reports_the_xml_failure_not_a_json_one():
    # Falling back means the failure that surfaces is the XML parse failure.
    r = run("//*", '"hello"')
    assert r.returncode == 1
    low = r.stderr.lower()
    assert "xml" in low or "parse" in low


def test_top_level_primitive_does_not_become_a_root_element():
    r = run("string(/root)", "123")
    assert r.returncode == 1
    assert r.stdout == ""


# ===========================================================================
# Section J3
# Phrase: "Input that fails JSON detection is parsed as XML/HTML."
# Context: Input Auto-Detection.
# ===========================================================================


def test_json_shaped_but_malformed_input_falls_back_to_xml():
    # T19: detection is a full parse, so `{oops}` is not JSON; it is handed to
    # the XML parser, which rejects it -- stderr, exit 1.
    r = run("//*", "{oops}")
    assert r.returncode == 1
    assert r.stderr.strip()


def test_trailing_garbage_after_json_is_not_json():
    r = run("//*", '{"a": 1} trailing')
    assert r.returncode == 1
    assert r.stderr.strip()


def test_html_ish_document_is_parsed_as_markup():
    doc = "<html><body><p>hi</p></body></html>"
    assert value("string(//p)", doc) == "hi"


def test_empty_input_still_fails_as_before():
    r = run("//*", "")
    assert r.returncode == 1
    assert r.stderr.strip()


# ===========================================================================
# Section J4
# Phrase: "Wrap converted documents in `<root>`."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_object_document_root_element_is_root():
    assert value("name(/*)", '{"a": 1}') == "root"


def test_array_document_root_element_is_root():
    assert value("name(/*)", "[1]") == "root"


def test_root_is_the_only_top_level_element():
    assert value("count(/*)", '{"a": 1, "b": 2}') == "1"


def test_empty_object_converts_to_an_empty_root():
    # T19: `{}` is a JSON object, so it is JSON input, not an XML error.
    assert tree("{}") == "<root/>\n"


def test_empty_array_converts_to_an_empty_root():
    assert tree("[]") == "<root/>\n"


# ===========================================================================
# Section J5
# Phrase: "`<root>` must not include `type`."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_root_has_no_type_attribute_for_object_input():
    r = run("/root/@type", '{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == ""


def test_root_has_no_type_attribute_for_array_input():
    r = run("/root/@type", "[1]")
    assert r.returncode == 0
    assert r.stdout == ""


def test_root_has_no_attributes_at_all():
    assert value("count(/root/@*)", '{"a": 1}') == "0"


def test_serialized_root_tag_carries_no_type():
    out = tree('{"a": 1}')
    assert out.startswith("<root>")


# ===========================================================================
# Section J6
# Phrase: "For top-level objects: keys become direct child elements."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_top_level_keys_are_direct_children_of_root():
    doc = '{"a": 1, "b": 2}'
    assert value("count(/root/a)", doc) == "1"
    assert value("count(/root/b)", doc) == "1"


def test_nested_object_keys_become_nested_elements():
    doc = '{"outer": {"inner": "v"}}'
    assert value("string(/root/outer/inner)", doc) == "v"


def test_object_conversion_is_recursive():
    doc = '{"a": {"b": {"c": 7}}}'
    assert value("string(/root/a/b/c)", doc) == "7"


# ===========================================================================
# Section J7
# Phrase: "For top-level arrays: each entry becomes an `<item>` child of
#          `<root>`."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_top_level_array_entries_are_item_children():
    doc = '["a", "b", "c"]'
    assert value("count(/root/item)", doc) == "3"
    assert run("/root/item/text()", doc).lines == ["a", "b", "c"]


def test_array_entries_keep_their_order():
    assert value("string(/root/item[2])", '["a", "b", "c"]') == "b"


def test_array_of_objects_gives_item_wrappers():
    doc = '[{"n": 1}, {"n": 2}]'
    assert run("/root/item/n/text()", doc).lines == ["1", "2"]


def test_nested_array_entries_are_also_items():
    # T22: `<item>` is the generic array-entry name at every depth.
    assert value("string(/root/a/item[1])", '{"a": [5, 6]}') == "5"


def test_array_inside_array():
    assert value("string(/root/item[1]/item[2])", "[[1, 2]]") == "2"


# ===========================================================================
# Section J8
# Phrase: "Object keys become element tag names (case preserved)."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_key_becomes_the_tag_name():
    assert value("name(/root/*[1])", '{"greeting": "hi"}') == "greeting"


def test_key_case_is_preserved():
    doc = '{"Foo": 1, "foo": 2}'
    assert value("string(/root/Foo)", doc) == "1"
    assert value("string(/root/foo)", doc) == "2"


def test_upper_case_key_does_not_match_lower_case_query():
    assert value("count(/root/item)", '{"Item": 1}') == "0"


def test_keys_with_legal_punctuation_are_kept_verbatim():
    doc = '{"a-b": 1, "a.b": 2, "_c": 3}'
    assert value("string(/root/*[1])", doc) == "1"
    assert value("name(/root/*[1])", doc) == "a-b"
    assert value("name(/root/*[2])", doc) == "a.b"
    assert value("name(/root/*[3])", doc) == "_c"


# ===========================================================================
# Section J9a
# Phrase: "Primitive values map to element text"
# Context: strings.
# ===========================================================================


def test_string_value_becomes_element_text():
    assert value("string(/root/a)", '{"a": "hello"}') == "hello"


def test_empty_string_value_gives_empty_text():
    r = run("/root/a/text()", '{"a": ""}')
    assert r.returncode == 0
    assert r.stdout == ""


def test_string_value_with_markup_is_escaped_not_parsed():
    doc = '{"a": "<b>x</b>"}'
    assert value("count(/root/a/*)", doc) == "0"
    assert value("string(/root/a)", doc) == "<b>x</b>"


# ===========================================================================
# Section J9b
# Phrase: "booleans as `true`/`false`"
# Context: primitive values map to element text.
# ===========================================================================


def test_true_becomes_the_text_true():
    assert value("string(/root/a)", '{"a": true}') == "true"


def test_false_becomes_the_text_false():
    assert value("string(/root/a)", '{"a": false}') == "false"


# ===========================================================================
# Section J9c
# Phrase: "numbers as minimal string form.
#          Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`,
#          `0.00012 -> "0.00012"`."
# Context: primitive values map to element text.
# ===========================================================================


@pytest.mark.parametrize(
    "literal,text",
    [
        ("1", "1"),
        ("1.0", "1"),
        ("1.50", "1.5"),
        ("0.00012", "0.00012"),
    ],
)
def test_spec_number_examples(literal, text):
    assert value("string(/root/a)", '{"a": %s}' % literal) == text


@pytest.mark.parametrize(
    "literal,text",
    [
        ("0", "0"),
        ("-3", "-3"),
        ("-2.50", "-2.5"),
        ("2.5", "2.5"),
        ("100.000", "100"),
        ("1E2", "100"),  # T20: integral floats collapse to the integer form
        ("3.14159", "3.14159"),
    ],
)
def test_more_number_forms(literal, text):
    assert value("string(/root/a)", '{"a": %s}' % literal) == text


def test_large_integer_is_not_truncated():
    big = "123456789012345678901234567890"
    assert value("string(/root/a)", '{"a": %s}' % big) == big


# ===========================================================================
# Section J9d
# Phrase: "null as empty"
# Context: primitive values map to element text.
# ===========================================================================


def test_null_has_no_text():
    r = run("/root/a/text()", '{"a": null}')
    assert r.returncode == 0
    assert r.stdout == ""


def test_null_string_value_is_empty():
    assert value("string(/root/a)", '{"a": null}') == ""


def test_null_element_still_exists():
    assert value("count(/root/a)", '{"a": null}') == "1"


# ===========================================================================
# Section J10
# Phrase: "Every converted element except `<root>` carries `type` in:
#          `str`, `int`, `float`, `bool`, `dict`, `list`, `null`."
# Context: JSON-to-XML Contract.
# ===========================================================================


@pytest.mark.parametrize(
    "literal,expected",
    [
        ('"x"', "str"),
        ("1", "int"),
        ("1.5", "float"),
        ("1.0", "float"),  # T21: typed from the JSON literal, not the value
        ("true", "bool"),
        ("false", "bool"),
        ("null", "null"),
        ("{}", "dict"),
        ('{"k": 1}', "dict"),
        ("[]", "list"),
        ("[1]", "list"),
    ],
)
def test_type_attribute_for_each_value_kind(literal, expected):
    assert value("string(/root/a/@type)", '{"a": %s}' % literal) == expected


def test_array_items_carry_type_too():
    doc = '[1, "x", null, true, 1.5, {}, []]'
    assert run("/root/item/@type", doc).lines == [
        "int",
        "str",
        "null",
        "bool",
        "float",
        "dict",
        "list",
    ]


def test_every_non_root_element_has_a_type():
    doc = '{"a": {"b": [1, {"c": null}]}, "d": "x"}'
    assert value("count(//*[not(self::root)])", doc) == value(
        "count(//*[not(self::root)][@type])", doc
    )


def test_type_is_selectable_as_an_attribute():
    doc = '{"a": 1, "b": "x", "c": 2}'
    assert run("//*[@type='int']/text()", doc).lines == ["1", "2"]


def test_no_element_uses_a_type_outside_the_vocabulary():
    doc = '{"a": 1, "b": 1.5, "c": "s", "d": true, "e": null, "f": {}, "g": []}'
    allowed = "|str|int|float|bool|dict|list|null|"
    query = "count(//@type[not(contains('%s', concat('|', ., '|')))])" % allowed
    assert value(query, doc) == "0"


# ===========================================================================
# Section J11
# Phrase: "Preserve JSON key order in converted XML."
# Context: JSON-to-XML Contract.
# ===========================================================================


def test_keys_keep_document_order_not_sorted_order():
    doc = '{"b": 1, "a": 2, "c": 3}'
    assert run("/root/*/@type", doc).lines == ["int", "int", "int"]
    assert value("name(/root/*[1])", doc) == "b"
    assert value("name(/root/*[2])", doc) == "a"
    assert value("name(/root/*[3])", doc) == "c"


def test_nested_object_key_order_is_preserved():
    doc = '{"x": {"z": 1, "y": 2}}'
    assert value("name(/root/x/*[1])", doc) == "z"
    assert value("name(/root/x/*[2])", doc) == "y"


def test_key_order_survives_in_the_serialized_tree():
    out = tree('{"b": "1", "a": "2"}')
    assert out.index("<b ") < out.index("<a ")


def test_duplicate_keys_keep_the_last_value():
    # T25: standard JSON parsing -- one element, last value wins.
    doc = '{"a": 1, "a": 2}'
    assert value("count(/root/a)", doc) == "1"
    assert value("string(/root/a)", doc) == "2"


# ===========================================================================
# Section J12
# Phrase: "JSON keys that are not valid XML element names are invalid input and
#          must produce stderr output with exit code `1` (include terms like
#          `json`/`key`/`invalid`)."
# Context: JSON-to-XML Contract.
# ===========================================================================


BAD_KEYS = ['"a b"', '"1a"', '""', '"a:b"', '"a/b"', '"<a>"', '"a,b"', '"#x"']


@pytest.mark.parametrize("key", BAD_KEYS)
def test_invalid_key_exits_one_with_stderr(key):
    r = run("//*", "{%s: 1}" % key)
    assert r.returncode == 1
    assert r.stderr.strip()


@pytest.mark.parametrize("key", BAD_KEYS)
def test_invalid_key_message_uses_the_expected_terms(key):
    r = run("//*", "{%s: 1}" % key)
    low = r.stderr.lower()
    assert "json" in low or "key" in low or "invalid" in low


def test_invalid_key_produces_no_stdout():
    r = run("//*", '{"a b": 1}')
    assert r.returncode == 1
    assert r.stdout == ""


def test_invalid_nested_key_is_also_rejected():
    # T24: the whole document is validated, not just the part the query reads.
    r = run("/root/ok", '{"ok": {"bad key": 1}}')
    assert r.returncode == 1
    assert r.stderr.strip()


def test_invalid_key_inside_an_array_entry_is_rejected():
    r = run("//*", '[{"bad key": 1}]')
    assert r.returncode == 1
    assert r.stderr.strip()


@pytest.mark.parametrize("key", ['"a"', '"_a"', '"a-b"', '"a.b"', '"A1"', '"xmlish"'])
def test_valid_keys_are_accepted(key):
    r = run("//*", "{%s: 1}" % key)
    assert r.returncode == 0
    assert r.stderr == ""


def test_bad_key_is_not_treated_as_a_json_syntax_error():
    # The document parses fine as JSON; only the key is unusable as a tag name.
    json.loads('{"a b": 1}')
    r = run("//*", '{"a b": 1}')
    assert r.returncode == 1


# ===========================================================================
# Integration
# Phrase: "Auto-detect stdin as JSON object/array or XML/HTML."
# Context: everything the earlier rounds specify keeps working on the converted
# document -- it is an ordinary XML tree.
# ===========================================================================


def test_serialized_conversion_of_a_mixed_document():
    doc = '{"name": "x", "n": 1.50, "ok": true, "sub": {"k": null}, "l": [1]}'
    assert tree(doc) == (
        "<root>\n"
        '  <name type="str">x</name>\n'
        '  <n type="float">1.5</n>\n'
        '  <ok type="bool">true</ok>\n'
        '  <sub type="dict">\n'
        '    <k type="null"/>\n'
        "  </sub>\n"
        '  <l type="list">\n'
        '    <item type="int">1</item>\n'
        "  </l>\n"
        "</root>\n"
    )


def test_css_selectors_work_on_converted_json():
    doc = '{"a": {"b": "deep"}}'
    r = run("--css", doc, "a b")
    assert r.returncode == 0
    assert "deep" in r.stdout


def test_css_text_pseudo_element_works_on_converted_json():
    doc = '[{"t": "one"}, {"t": "two"}]'
    r = run("--css", doc, "t::text")
    assert r.returncode == 0
    assert r.lines == ["one", "two"]


def test_text_flag_works_on_converted_json():
    doc = '{"a": "x", "b": "y"}'
    r = run("//root/*", doc, "-t")
    assert r.returncode == 0
    assert r.lines == ["x", "y"]
