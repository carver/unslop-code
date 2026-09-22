"""Tests for the "JSON Input and Auto-Detection" spec, phrase by phrase."""

import json

import pytest


# --- "Auto-detect stdin as JSON object/array or XML/HTML." -------------------


def test_top_level_json_object_is_detected_and_queryable(run_xjq):
    result = run_xjq("//a/text()", stdin='{"a": "hello"}')
    assert result.returncode == 0
    assert result.lines == ["hello"]


def test_top_level_json_array_is_detected_and_queryable(run_xjq):
    result = run_xjq("//item/text()", stdin="[1, 2]")
    assert result.returncode == 0
    assert result.lines == ["1", "2"]


def test_xml_input_is_still_detected_as_xml(run_xjq):
    result = run_xjq("//a/text()", stdin="<doc><a>hello</a></doc>")
    assert result.returncode == 0
    assert result.lines == ["hello"]


def test_json_detection_tolerates_surrounding_whitespace(run_xjq):
    result = run_xjq("//a/text()", stdin='\n\t  {"a": 1}  \n')
    assert result.returncode == 0
    assert result.lines == ["1"]


def test_auto_detection_applies_in_css_mode_too(run_xjq):
    result = run_xjq("--css", "a::text", stdin='{"a": "hello"}')
    assert result.returncode == 0
    assert result.lines == ["hello"]


# --- "Top-level JSON primitives are not accepted as JSON input for this mode;
#      they fall back to XML parsing." ---------------------------------------


@pytest.mark.parametrize("primitive", ['"hello"', "42", "1.5", "true", "false", "null"])
def test_top_level_primitives_fall_back_to_xml_parsing(run_xjq, primitive):
    result = run_xjq("//*", stdin=primitive)
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()
    assert result.stdout == ""


def test_top_level_primitive_that_is_valid_xml_is_parsed_as_xml(run_xjq):
    # `<null/>` is not JSON at all, but the point is that the XML branch owns
    # anything the JSON object/array branch declines.
    result = run_xjq("name(/*)", stdin="<null/>")
    assert result.returncode == 0
    assert result.lines == ["null"]


# --- "Input that fails JSON detection is parsed as XML/HTML." ----------------


def test_malformed_json_object_falls_back_to_xml_and_fails_there(run_xjq):
    result = run_xjq("//a", stdin='{"a": ')
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


def test_json_like_xml_document_is_parsed_as_xml(run_xjq):
    result = run_xjq("//a/text()", stdin='<r><a>{"not": "json"}</a></r>')
    assert result.returncode == 0
    assert result.lines == ['{"not": "json"}']


def test_empty_stdin_still_reports_an_input_error(run_xjq):
    result = run_xjq("//a", stdin="")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# --- "Wrap converted documents in `<root>`." ---------------------------------


def test_converted_object_is_wrapped_in_root(run_xjq):
    result = run_xjq("name(/*)", stdin='{"a": 1}')
    assert result.lines == ["root"]


def test_converted_array_is_wrapped_in_root(run_xjq):
    result = run_xjq("name(/*)", stdin="[1]")
    assert result.lines == ["root"]


def test_empty_object_converts_to_a_childless_root(run_xjq):
    result = run_xjq("count(/root/*)", stdin="{}")
    assert result.returncode == 0
    assert result.lines == ["0"]


def test_empty_array_converts_to_a_childless_root(run_xjq):
    result = run_xjq("count(/root/*)", stdin="[]")
    assert result.returncode == 0
    assert result.lines == ["0"]


# --- "`<root>` must not include `type`." -------------------------------------


def test_root_has_no_type_attribute_for_objects(run_xjq):
    result = run_xjq("count(/root/@type)", stdin='{"a": 1}')
    assert result.lines == ["0"]


def test_root_has_no_type_attribute_for_arrays(run_xjq):
    result = run_xjq("count(/root/@type)", stdin="[1]")
    assert result.lines == ["0"]


def test_root_carries_no_attributes_at_all(run_xjq):
    result = run_xjq("count(/root/@*)", stdin='{"a": 1}')
    assert result.lines == ["0"]


def test_rendered_root_element_shows_no_type(run_xjq):
    result = run_xjq("/root", stdin='{"a": 1}')
    assert result.returncode == 0
    assert result.stdout.startswith("<root>")


# --- "For top-level objects: keys become direct child elements." -------------


def test_object_keys_become_direct_children_of_root(run_xjq):
    result = run_xjq("name(/root/*)", stdin='{"alpha": 1, "beta": 2}')
    assert result.lines == ["alpha"]


def test_every_object_key_yields_one_child(run_xjq):
    result = run_xjq("count(/root/*)", stdin='{"a": 1, "b": 2, "c": 3}')
    assert result.lines == ["3"]


def test_nested_object_keys_become_children_of_their_own_element(run_xjq):
    result = run_xjq("/root/outer/inner/text()", stdin='{"outer": {"inner": "x"}}')
    assert result.lines == ["x"]


# --- "For top-level arrays: each entry becomes an `<item>` child of `<root>`."


def test_array_entries_become_item_children(run_xjq):
    result = run_xjq("count(/root/item)", stdin='["a", "b", "c"]')
    assert result.lines == ["3"]


def test_array_item_children_are_the_only_children(run_xjq):
    result = run_xjq("count(/root/*) - count(/root/item)", stdin="[1, 2]")
    assert result.lines == ["0"]


def test_array_entries_keep_their_order(run_xjq):
    result = run_xjq("//item/text()", stdin='["first", "second", "third"]')
    assert result.lines == ["first", "second", "third"]


def test_nested_array_entries_also_become_items(run_xjq):
    result = run_xjq("/root/nums/item/text()", stdin='{"nums": [10, 20]}')
    assert result.lines == ["10", "20"]


# --- "Object keys become element tag names (case preserved)." ----------------


def test_key_case_is_preserved(run_xjq):
    result = run_xjq("name(/root/*)", stdin='{"FooBar": 1}')
    assert result.lines == ["FooBar"]


def test_key_case_matters_when_querying(run_xjq):
    result = run_xjq("count(/root/foobar)", stdin='{"FooBar": 1}')
    assert result.lines == ["0"]


def test_keys_differing_only_in_case_stay_distinct(run_xjq):
    result = run_xjq("count(/root/*)", stdin='{"a": 1, "A": 2}')
    assert result.lines == ["2"]


# --- "Primitive values map to element text: booleans as `true`/`false`,
#      numbers as minimal string form, null as empty." -----------------------


def test_string_value_becomes_element_text(run_xjq):
    result = run_xjq("/root/a/text()", stdin='{"a": "hello"}')
    assert result.lines == ["hello"]


@pytest.mark.parametrize(
    ("value", "text"), [("true", "true"), ("false", "false")]
)
def test_booleans_render_lowercase(run_xjq, value, text):
    result = run_xjq("/root/a/text()", stdin='{"a": %s}' % value)
    assert result.lines == [text]


@pytest.mark.parametrize(
    ("literal", "text"),
    [
        ("1", "1"),
        ("1.0", "1"),
        ("1.50", "1.5"),
        ("0.00012", "0.00012"),
        ("-3", "-3"),
        ("0", "0"),
        ("2.5", "2.5"),
    ],
)
def test_numbers_use_their_minimal_string_form(run_xjq, literal, text):
    result = run_xjq("/root/a/text()", stdin='{"a": %s}' % literal)
    assert result.lines == [text]


def test_null_has_empty_text(run_xjq):
    result = run_xjq("count(/root/a/text())", stdin='{"a": null}')
    assert result.lines == ["0"]


def test_null_element_string_value_is_empty(run_xjq):
    result = run_xjq("string-length(/root/a)", stdin='{"a": null}')
    assert result.lines == ["0"]


def test_special_characters_in_text_survive_the_round_trip(run_xjq):
    result = run_xjq("/root/a/text()", stdin=json.dumps({"a": "x < y & z"}))
    assert result.lines == ["x < y & z"]


# --- "Every converted element except `<root>` carries `type` in:
#      `str`, `int`, `float`, `bool`, `dict`, `list`, `null`." ---------------


@pytest.mark.parametrize(
    ("literal", "type_name"),
    [
        ('"s"', "str"),
        ("7", "int"),
        ("7.5", "float"),
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
def test_value_elements_carry_the_matching_type(run_xjq, literal, type_name):
    result = run_xjq("/root/a/@type", stdin='{"a": %s}' % literal)
    assert result.lines == [type_name]


def test_array_items_carry_their_own_type(run_xjq):
    result = run_xjq("//item/@type", stdin='[1, "s", null, true, 1.5, {}, []]')
    assert result.lines == ["int", "str", "null", "bool", "float", "dict", "list"]


def test_nested_elements_all_carry_a_type(run_xjq):
    stdin = '{"a": {"b": [1]}}'
    result = run_xjq("count(//*[not(self::root)][not(@type)])", stdin=stdin)
    assert result.lines == ["0"]


def test_type_is_the_only_attribute_on_converted_elements(run_xjq):
    result = run_xjq("count(//a/@*)", stdin='{"a": {"b": 1}}')
    assert result.lines == ["1"]


def test_type_supports_filtering_by_kind(run_xjq):
    stdin = '{"a": 1, "b": "x", "c": 2}'
    result = run_xjq('//*[@type="int"]/text()', stdin=stdin)
    assert result.lines == ["1", "2"]


# --- "Preserve JSON key order in converted XML." -----------------------------


def test_keys_keep_document_order_not_sorted_order(run_xjq):
    result = run_xjq("//*[not(self::root)]/text()", stdin='{"z": 1, "a": 2, "m": 3}')
    assert result.lines == ["1", "2", "3"]


def test_first_child_is_the_first_key(run_xjq):
    result = run_xjq("name(/root/*[1])", stdin='{"zebra": 1, "apple": 2}')
    assert result.lines == ["zebra"]


def test_last_child_is_the_last_key(run_xjq):
    result = run_xjq("name(/root/*[last()])", stdin='{"zebra": 1, "apple": 2}')
    assert result.lines == ["apple"]


def test_nested_objects_preserve_their_own_key_order(run_xjq):
    stdin = '{"outer": {"c": 1, "b": 2, "a": 3}}'
    result = run_xjq("name(/root/outer/*[1])", stdin=stdin)
    assert result.lines == ["c"]


# --- "JSON keys that are not valid XML element names are invalid input and
#      must produce stderr output with exit code `1` (include terms like
#      `json`/`key`/`invalid`)." ---------------------------------------------


@pytest.mark.parametrize(
    "key", ["a b", "1a", "", "a:b", "-x", ".x", "a/b", "#", "a(b)", "a,b"]
)
def test_keys_that_are_not_xml_names_are_rejected(run_xjq, key):
    result = run_xjq("//*", stdin=json.dumps({key: 1}))
    assert result.returncode == 1
    assert result.stdout == ""
    lowered = result.stderr.lower()
    assert "json" in lowered and "key" in lowered and "invalid" in lowered


@pytest.mark.parametrize("key", ["a", "_a", "a-b", "a.b", "a1", "xml", "Ünicode"])
def test_keys_that_are_valid_xml_names_are_accepted(run_xjq, key):
    result = run_xjq("count(/root/*)", stdin=json.dumps({key: 1}))
    assert result.returncode == 0
    assert result.lines == ["1"]


def test_invalid_key_nested_deep_is_also_rejected(run_xjq):
    stdin = json.dumps({"ok": [{"still ok?": 1}]})
    result = run_xjq("//*", stdin=stdin)
    assert result.returncode == 1
    assert "json" in result.stderr.lower()


def test_invalid_key_is_reported_before_the_query_runs(run_xjq):
    result = run_xjq("//[[[", stdin=json.dumps({"a b": 1}))
    assert result.returncode == 1
    assert "json" in result.stderr.lower()


def test_invalid_key_inside_a_string_value_is_harmless(run_xjq):
    result = run_xjq("/root/a/text()", stdin=json.dumps({"a": "not a key"}))
    assert result.returncode == 0
    assert result.lines == ["not a key"]
