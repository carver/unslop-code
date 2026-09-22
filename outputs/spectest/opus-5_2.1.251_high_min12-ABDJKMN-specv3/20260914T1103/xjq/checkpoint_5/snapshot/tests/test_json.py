"""Spec section: JSON Input and Auto-Detection.

Each test section quotes the minimal spec phrase it covers.
"""
import json

import pytest


# --- Phrase: "Auto-detect stdin as JSON object/array or XML/HTML." --------
# Context: no flag is given; the input kind is decided from the bytes.

def test_top_level_json_object_is_detected(xjq):
    r = xjq("/root/a/text()", stdin='{"a": "x"}')
    assert r.returncode == 0
    assert r.stdout == "x"


def test_top_level_json_array_is_detected(xjq):
    r = xjq("/root/item/text()", stdin='[1, 2, 3]')
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "2", "3"]


def test_xml_input_is_still_detected_as_xml(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


def test_html_input_is_still_detected_as_html(xjq):
    doc = "<!DOCTYPE html><html><body><p>hi<p>there</body></html>"
    r = xjq("//p/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["hi", "there"]


def test_json_object_with_leading_whitespace_is_detected(xjq):
    r = xjq("/root/a/text()", stdin='\n\n   {"a": "x"}\n')
    assert r.returncode == 0
    assert r.stdout == "x"


def test_json_array_with_leading_whitespace_is_detected(xjq):
    r = xjq("/root/item/text()", stdin='   \n[1]')
    assert r.returncode == 0
    assert r.stdout == "1"


def test_detection_does_not_need_a_flag(xjq):
    r = xjq("//b/text()", stdin='{"a": {"b": "deep"}}')
    assert r.returncode == 0
    assert r.stdout == "deep"


def test_json_detection_works_with_css_mode(xjq):
    r = xjq("--css", "a", stdin='{"a": "x"}')
    assert r.returncode == 0
    assert "<a" in r.stdout


def test_json_detection_works_with_text_flag(xjq):
    r = xjq("-t", "//a", stdin='{"a": "x"}')
    assert r.returncode == 0
    assert r.stdout == "x"


# --- Phrase: "Top-level JSON primitives are not accepted as JSON input ----
# for this mode; they fall back to XML parsing."
# Context: a bare number/string/bool/null on stdin is not JSON input here.

@pytest.mark.parametrize(
    "primitive",
    ["123", '"hello"', "true", "false", "null", "1.5", "-4", '  7  '],
)
def test_top_level_primitive_is_not_json(xjq, primitive):
    # Falls back to XML, which cannot parse it -> the XML error path.
    r = xjq("/root", stdin=primitive)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_top_level_primitive_does_not_produce_a_root(xjq):
    r = xjq("/root/text()", stdin="123")
    assert r.returncode == 1
    assert r.stdout == ""


def test_string_that_looks_like_xml_falls_back_to_xml(xjq):
    # A JSON string is a top-level primitive, so the raw bytes go to XML.
    r = xjq("/a/text()", stdin="<a>hi</a>")
    assert r.returncode == 0
    assert r.stdout == "hi"


# --- Phrase: "Input that fails JSON detection is parsed as XML/HTML." -----
# Context: text that starts like JSON but is not valid JSON.

@pytest.mark.parametrize(
    "broken",
    ['{"a": 1', '{a: 1}', "[1, 2", "{,}", "[}", "{'a': 1}", "[1, 2,]"],
)
def test_malformed_json_falls_back_to_xml(xjq, broken):
    r = xjq("/root", stdin=broken)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_fallback_error_is_the_xml_error(xjq):
    r = xjq("//a", stdin='{"a": 1')
    assert r.returncode == 1
    assert "xml" in r.stderr.lower()


def test_empty_input_is_still_an_xml_error(xjq):
    r = xjq("//a", stdin="")
    assert r.returncode == 1
    assert r.stdout == ""


# --- Phrase: "Wrap converted documents in `<root>`." ---------------------
# Context: the converted tree always has a single <root> document element.

def test_object_document_element_is_root(xjq):
    r = xjq("name(/*)", stdin='{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == "root"


def test_array_document_element_is_root(xjq):
    r = xjq("name(/*)", stdin='[1]')
    assert r.returncode == 0
    assert r.stdout == "root"


def test_root_is_the_only_top_level_element(xjq):
    r = xjq("count(/*)", stdin='{"a": 1, "b": 2}')
    assert r.returncode == 0
    assert r.stdout == "1"


def test_root_serializes_as_root_element(xjq):
    r = xjq("/root", stdin='{"a": "x"}')
    assert r.returncode == 0
    assert r.stdout.startswith("<root>")


# --- Phrase: "`<root>` must not include `type`." -------------------------
# Context: the wrapper element carries no type attribute.

def test_root_has_no_type_attribute(xjq):
    r = xjq("/root/@type", stdin='{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == ""


def test_root_has_no_attributes_at_all(xjq):
    r = xjq("count(/root/@*)", stdin='{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == "0"


def test_root_of_array_has_no_type_attribute(xjq):
    r = xjq("count(/root/@*)", stdin='[1, 2]')
    assert r.returncode == 0
    assert r.stdout == "0"


def test_root_tag_is_not_self_described_in_output(xjq):
    r = xjq("/root", stdin='[1]')
    assert r.returncode == 0
    assert 'type=' not in r.stdout.splitlines()[0]


# --- Phrase: "For top-level objects: keys become direct child elements." --
# Context: one child element per key, directly under <root>.

def test_object_keys_become_children_of_root(xjq):
    r = xjq("name(/root/*[1])", stdin='{"alpha": 1, "beta": 2}')
    assert r.returncode == 0
    assert r.stdout == "alpha"


def test_object_produces_one_child_per_key(xjq):
    r = xjq("count(/root/*)", stdin='{"a": 1, "b": 2, "c": 3}')
    assert r.returncode == 0
    assert r.stdout == "3"


def test_object_children_are_direct(xjq):
    r = xjq("/root/b/text()", stdin='{"a": 1, "b": "two"}')
    assert r.returncode == 0
    assert r.stdout == "two"


def test_empty_object_has_no_children(xjq):
    r = xjq("count(/root/*)", stdin="{}")
    assert r.returncode == 0
    assert r.stdout == "0"


# --- Phrase: "For top-level arrays: each entry becomes an `<item>` child --
# of `<root>`."
# Context: array entries are named <item>, in order, under <root>.

def test_array_entries_become_item_children(xjq):
    r = xjq("count(/root/item)", stdin='["a", "b", "c"]')
    assert r.returncode == 0
    assert r.stdout == "3"


def test_array_items_are_the_only_children(xjq):
    r = xjq("count(/root/*) - count(/root/item)", stdin='[1, 2]')
    assert r.returncode == 0
    assert r.stdout == "0"


def test_array_item_order_is_preserved(xjq):
    r = xjq("/root/item/text()", stdin='["x", "y", "z"]')
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["x", "y", "z"]


def test_empty_array_has_no_children(xjq):
    r = xjq("count(/root/*)", stdin="[]")
    assert r.returncode == 0
    assert r.stdout == "0"


def test_nested_array_entries_also_become_items(xjq):
    r = xjq("/root/nums/item/text()", stdin='{"nums": [1, 2]}')
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "2"]


def test_array_of_objects_keeps_keys_under_item(xjq):
    doc = '[{"n": 1}, {"n": 2}]'
    r = xjq("/root/item/n/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "2"]


# --- Phrase: "Object keys become element tag names (case preserved)." -----
# Context: the key string is used verbatim as the tag name.

def test_key_becomes_tag_name(xjq):
    r = xjq("name(/root/*[1])", stdin='{"Title": "x"}')
    assert r.returncode == 0
    assert r.stdout == "Title"


def test_key_case_is_preserved(xjq):
    r = xjq("count(/root/FooBar)", stdin='{"FooBar": 1}')
    assert r.returncode == 0
    assert r.stdout == "1"


def test_upper_and_lower_keys_are_distinct(xjq):
    r = xjq("/root/A/text()", stdin='{"a": "low", "A": "up"}')
    assert r.returncode == 0
    assert r.stdout == "up"


def test_key_case_preserved_when_nested(xjq):
    r = xjq("/root/Outer/InNer/text()", stdin='{"Outer": {"InNer": "v"}}')
    assert r.returncode == 0
    assert r.stdout == "v"


def test_key_with_underscores_and_digits(xjq):
    r = xjq("/root/a_1-b.c/text()", stdin='{"a_1-b.c": "v"}')
    assert r.returncode == 0
    assert r.stdout == "v"


# --- Phrase: "Primitive values map to element text: booleans as ----------
# `true`/`false`"
# Context: JSON true/false become the literal words.

def test_boolean_true_text(xjq):
    r = xjq("/root/a/text()", stdin='{"a": true}')
    assert r.returncode == 0
    assert r.stdout == "true"


def test_boolean_false_text(xjq):
    r = xjq("/root/a/text()", stdin='{"a": false}')
    assert r.returncode == 0
    assert r.stdout == "false"


def test_booleans_are_not_python_cased(xjq):
    r = xjq("/root", stdin='{"a": true, "b": false}')
    assert r.returncode == 0
    assert "True" not in r.stdout and "False" not in r.stdout


# --- Phrase: "numbers as minimal string form" ----------------------------
# Context: the spec's own examples, plus the int/float shapes around them.

@pytest.mark.parametrize(
    "literal,expected",
    [
        ("1", "1"),
        ("1.0", "1"),
        ("1.50", "1.5"),
        ("0.00012", "0.00012"),
        ("0", "0"),
        ("-3", "-3"),
        ("-2.5", "-2.5"),
        ("100", "100"),
        ("2.000", "2"),
        ("3.14159", "3.14159"),
    ],
)
def test_number_minimal_string_form(xjq, literal, expected):
    r = xjq("/root/a/text()", stdin='{"a": %s}' % literal)
    assert r.returncode == 0
    assert r.stdout == expected


def test_large_integer_is_not_truncated(xjq):
    r = xjq("/root/a/text()", stdin='{"a": 9007199254740993}')
    assert r.returncode == 0
    assert r.stdout == "9007199254740993"


def test_number_in_array_uses_minimal_form(xjq):
    r = xjq("/root/item/text()", stdin='[1.0, 1.50, 0.00012]')
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "1.5", "0.00012"]


# --- Phrase: "null as empty (no self-closing tags)" ----------------------
# Context: a JSON null element has empty text and an explicit end tag.

def test_null_has_empty_text(xjq):
    r = xjq("string(/root/a)", stdin='{"a": null}')
    assert r.returncode == 0
    assert r.stdout == ""


def test_null_element_exists(xjq):
    r = xjq("count(/root/a)", stdin='{"a": null}')
    assert r.returncode == 0
    assert r.stdout == "1"


def test_null_is_not_self_closing(xjq):
    r = xjq("/root", stdin='{"a": null}')
    assert r.returncode == 0
    assert "/>" not in r.stdout
    assert "</a>" in r.stdout


def test_null_in_array_is_not_self_closing(xjq):
    r = xjq("/root", stdin='[null]')
    assert r.returncode == 0
    assert "</item>" in r.stdout
    assert "/>" not in r.stdout


def test_null_does_not_render_the_word_none(xjq):
    r = xjq("/root", stdin='{"a": null}')
    assert r.returncode == 0
    assert "None" not in r.stdout
    assert "null<" not in r.stdout


# --- Phrase: "Primitive values map to element text" (strings) ------------
# Context: string values land verbatim as the element's text.

def test_string_value_text(xjq):
    r = xjq("/root/a/text()", stdin='{"a": "hello"}')
    assert r.returncode == 0
    assert r.stdout == "hello"


def test_string_value_is_xml_escaped(xjq):
    r = xjq("/root", stdin=json.dumps({"a": "<b>&x"}))
    assert r.returncode == 0
    assert "&lt;b&gt;&amp;x" in r.stdout


def test_string_value_round_trips_through_xpath(xjq):
    r = xjq("/root/a/text()", stdin=json.dumps({"a": "<b>&x"}))
    assert r.returncode == 0
    assert r.stdout == "<b>&x"


def test_unicode_string_value(xjq):
    r = xjq("/root/a/text()", stdin=json.dumps({"a": "café ☕"}))
    assert r.returncode == 0
    assert r.stdout == "café ☕"


# --- Phrase: "Every converted element except `<root>` carries `type` in: --
# `str`, `int`, `float`, `bool`, `dict`, `list`, `null`."
# Context: the type attribute names the JSON value's Python-ish type.

@pytest.mark.parametrize(
    "literal,expected",
    [
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
    ],
)
def test_type_attribute_value(xjq, literal, expected):
    r = xjq("/root/a/@type", stdin='{"a": %s}' % literal)
    assert r.returncode == 0
    assert r.stdout == expected


def test_every_non_root_element_has_a_type(xjq):
    doc = '{"a": 1, "b": {"c": [null, "s"]}}'
    r = xjq("count(//*) - count(//*[@type]) - 1", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "0"


def test_item_elements_carry_type(xjq):
    r = xjq("/root/item/@type", stdin='[1, "x", true]')
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["int", "str", "bool"]


def test_nested_item_carries_type(xjq):
    r = xjq("/root/item/item/@type", stdin='[[1.5]]')
    assert r.returncode == 0
    assert r.stdout == "float"


def test_type_values_are_limited_to_the_named_set(xjq):
    doc = '{"a": 1, "b": 1.5, "c": "s", "d": true, "e": null, "f": {}, "g": []}'
    r = xjq("//@type", stdin=doc)
    assert r.returncode == 0
    allowed = {"str", "int", "float", "bool", "dict", "list", "null"}
    assert set(r.stdout.splitlines()) <= allowed


def test_bool_is_not_reported_as_int(xjq):
    r = xjq("/root/a/@type", stdin='{"a": true}')
    assert r.returncode == 0
    assert r.stdout == "bool"


# --- Phrase: "Preserve JSON key order in converted XML." -----------------
# Context: document order matches the order keys appear in the JSON text.

def test_key_order_is_preserved(xjq):
    doc = '{"zebra": 1, "apple": 2, "mango": 3}'
    r = xjq("name(/root/*)", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "zebra"


def test_key_order_is_preserved_in_serialized_output(xjq):
    doc = '{"zebra": 1, "apple": 2, "mango": 3}'
    r = xjq("/root", stdin=doc)
    assert r.returncode == 0
    order = [
        line.strip().split(" ")[0].lstrip("<")
        for line in r.stdout.splitlines()
        if line.strip().startswith("<") and not line.strip().startswith("<root")
        and not line.strip().startswith("</")
    ]
    assert order == ["zebra", "apple", "mango"]


def test_nested_key_order_is_preserved(xjq):
    doc = '{"o": {"c": 1, "a": 2, "b": 3}}'
    r = xjq("name(/root/o/*[2])", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "a"


def test_key_order_is_not_sorted(xjq):
    doc = '{"b": 1, "a": 2}'
    r = xjq("name(/root/*[1])", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "b"


# --- Phrase: "JSON keys that are not valid XML element names are invalid -
# input and must produce stderr output with exit code `1`"
# Context: the key cannot be used as a tag name.

@pytest.mark.parametrize(
    "key",
    ["a b", "1a", "", "a b c", "-x", ".y", "a/b", "a>b", "#hash", "a=b", " ", "@at"],
)
def test_invalid_key_exits_one(xjq, key):
    r = xjq("//*", stdin=json.dumps({key: 1}))
    assert r.returncode == 1


def test_invalid_key_writes_to_stderr(xjq):
    r = xjq("//*", stdin='{"a b": 1}')
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_invalid_key_writes_nothing_to_stdout(xjq):
    r = xjq("//*", stdin='{"a b": 1}')
    assert r.stdout == ""


# --- Phrase: "(include terms like `json`/`key`/`invalid`)" ---------------
# Context: the stderr message must be recognisable as a JSON key problem.

def test_invalid_key_message_mentions_json(xjq):
    r = xjq("//*", stdin='{"a b": 1}')
    assert "json" in r.stderr.lower()


def test_invalid_key_message_mentions_key(xjq):
    r = xjq("//*", stdin='{"a b": 1}')
    assert "key" in r.stderr.lower()


def test_invalid_key_message_mentions_invalid(xjq):
    r = xjq("//*", stdin='{"a b": 1}')
    assert "invalid" in r.stderr.lower()


def test_nested_invalid_key_is_also_rejected(xjq):
    r = xjq("//*", stdin='{"ok": {"bad key": 1}}')
    assert r.returncode == 1
    assert "key" in r.stderr.lower()


def test_invalid_key_inside_array_object_is_rejected(xjq):
    r = xjq("//*", stdin='[{"bad key": 1}]')
    assert r.returncode == 1
    assert "key" in r.stderr.lower()


def test_valid_keys_do_not_error(xjq):
    r = xjq("count(//*)", stdin='{"_a": 1, "b-c": 2, "d.e": 3, "f9": 4}')
    assert r.returncode == 0
    assert r.stdout == "5"


# --- Cross-phrase: the converted tree is queryable like any XML ----------
# Context: JSON conversion feeds the existing query/output pipeline.

def test_xpath_predicate_on_type_attribute(xjq):
    doc = '{"a": 1, "b": "s", "c": 2}'
    r = xjq("//*[@type='int']/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1", "2"]


def test_css_selector_on_converted_json(xjq):
    doc = '{"a": {"b": "deep"}}'
    r = xjq("--css", "a b::text", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "deep"


def test_text_all_on_converted_json(xjq):
    doc = '{"a": {"b": "x", "c": "y"}}'
    r = xjq("--text-all", "//a", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "xy"


def test_converted_output_is_pretty_printed(xjq):
    r = xjq("/root", stdin='{"a": {"b": 1}}')
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert lines[0] == "<root>"
    assert lines[1].startswith("  <a")
    assert lines[2].startswith("    <b")


def test_no_match_on_converted_json_is_silent(xjq):
    r = xjq("//nope", stdin='{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == ""
