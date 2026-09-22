"""Spec tests for JSON input auto-detection, one section per phrase."""

import subprocess
import sys
from pathlib import Path

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"

OBJECT = b'{"name": "widget", "count": 2}'
ARRAY = b'[10, 20]'
XML = b"<Root><Item>first</Item></Root>"


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


def json_doc(body):
    """Wrap `body` as the sole value of a top-level object under key `v`."""
    return f'{{"v": {body}}}'.encode()


def value_of(body, query="/root/v/text()"):
    """Query the converted element for a single JSON value."""
    return out(run(query, stdin=json_doc(body)))


def type_of(body):
    """The `type` attribute of the element for a single JSON value."""
    return value_of(body, "/root/v/@type")


# --- Auto-Detection: "Auto-detect stdin as JSON object/array or XML/HTML." ---


def test_top_level_object_is_detected_as_json():
    result = run("/root/name/text()", stdin=OBJECT)
    assert result.returncode == 0
    assert out(result) == "widget"


def test_top_level_array_is_detected_as_json():
    result = run("/root/item[1]/text()", stdin=ARRAY)
    assert result.returncode == 0
    assert out(result) == "10"


def test_xml_input_is_still_detected_as_xml():
    result = run("//Item/text()", stdin=XML)
    assert result.returncode == 0
    assert out(result) == "first"


def test_detection_ignores_surrounding_whitespace():
    result = run("/root/name/text()", stdin=b"\n  " + OBJECT + b"\n")
    assert out(result) == "widget"


def test_html_shaped_input_is_not_detected_as_json():
    result = run("//li/text()", stdin=b"<ul><li>a</li></ul>")
    assert out(result) == "a"


# --- Auto-Detection: "Top-level JSON primitives are not accepted as JSON ---
# --- input for this mode; they fall back to XML parsing." -------------------


def test_top_level_number_falls_back_to_xml():
    # `123` is valid JSON but a primitive, so it is handed to the XML parser,
    # which rejects it.
    result = run("/root", stdin=b"123")
    assert result.returncode == 1
    assert err(result) != ""


def test_top_level_string_falls_back_to_xml():
    result = run("/root", stdin=b'"widget"')
    assert result.returncode == 1
    assert out(result) == ""


def test_top_level_boolean_falls_back_to_xml():
    result = run("/root", stdin=b"true")
    assert result.returncode == 1


def test_top_level_null_falls_back_to_xml():
    result = run("/root", stdin=b"null")
    assert result.returncode == 1


def test_primitive_fallback_reports_an_xml_error():
    # The fallback parser owns the message, so it references xml/parse.
    result = run("/root", stdin=b"123")
    assert any(term in err(result).lower() for term in ("xml", "parse"))


def test_primitive_that_is_valid_xml_is_parsed_as_xml():
    # A JSON primitive spelled as markup parses fine on the fallback path.
    result = run("/a/text()", stdin=b"<a>123</a>")
    assert out(result) == "123"


# --- Auto-Detection: "Input that fails JSON detection is parsed as ---------
# --- XML/HTML." ------------------------------------------------------------


def test_malformed_json_object_falls_back_to_xml():
    result = run("/root", stdin=b'{"name": }')
    assert result.returncode == 1
    assert any(term in err(result).lower() for term in ("xml", "parse"))


def test_truncated_json_array_falls_back_to_xml():
    result = run("/root", stdin=b"[1, 2")
    assert result.returncode == 1


def test_json_with_trailing_garbage_falls_back_to_xml():
    result = run("/root", stdin=OBJECT + b" trailing")
    assert result.returncode == 1


def test_empty_input_is_still_an_error():
    result = run("/root", stdin=b"")
    assert result.returncode == 1


# --- Contract: "Wrap converted documents in `<root>`." ---------------------


def test_converted_object_is_wrapped_in_root():
    assert out(run("name(/*)", stdin=OBJECT)) == "root"


def test_converted_array_is_wrapped_in_root():
    assert out(run("name(/*)", stdin=ARRAY)) == "root"


# --- Contract: "`<root>` must not include `type`." -------------------------


def test_root_has_no_type_attribute_for_objects():
    assert out(run("count(/root/@*)", stdin=OBJECT)) == "0"


def test_root_has_no_type_attribute_for_arrays():
    assert out(run("count(/root/@type)", stdin=ARRAY)) == "0"


# --- Contract: "For top-level objects: keys become direct child elements." -


def test_top_level_keys_are_direct_children_of_root():
    assert out(run("count(/root/*)", stdin=OBJECT)) == "2"


def test_each_top_level_key_names_one_child():
    assert out(run("/root/count/text()", stdin=OBJECT)) == "2"


# --- Contract: "For top-level arrays: each entry becomes an `<item>` -------
# --- child of `<root>`." ---------------------------------------------------


def test_array_entries_become_item_children():
    assert out(run("/root/item/text()", stdin=ARRAY)) == "10\n20"


def test_array_entries_use_the_item_tag_only():
    assert out(run("count(/root/item)", stdin=ARRAY)) == "2"


def test_nested_arrays_also_use_item():
    assert out(run("/root/v/item/text()", stdin=json_doc("[1, 2]"))) == "1\n2"


# --- Contract: "Object keys become element tag names (case preserved)." ----


def test_key_case_is_preserved():
    assert out(run("/root/Name/text()", stdin=b'{"Name": "widget"}')) == "widget"


def test_key_case_is_not_folded():
    assert out(run("count(/root/name)", stdin=b'{"Name": "x"}')) == "0"


def test_nested_keys_become_elements():
    doc = b'{"outer": {"Inner": "deep"}}'
    assert out(run("/root/outer/Inner/text()", stdin=doc)) == "deep"


# --- Contract: "Primitive values map to element text: booleans as ----------
# --- `true`/`false`" -------------------------------------------------------


def test_true_maps_to_the_text_true():
    assert value_of("true") == "true"


def test_false_maps_to_the_text_false():
    assert value_of("false") == "false"


# --- Contract: "numbers as minimal string form. Examples: `1 -> "1"`, ------
# --- `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`" ----------------


def test_integer_one_renders_as_1():
    assert value_of("1") == "1"


def test_float_one_point_zero_renders_as_1():
    assert value_of("1.0") == "1"


def test_trailing_zero_is_dropped():
    assert value_of("1.50") == "1.5"


def test_small_fraction_keeps_its_digits():
    assert value_of("0.00012") == "0.00012"


def test_negative_number_keeps_its_sign():
    assert value_of("-2.5") == "-2.5"


# --- Contract: "null as empty (no self-closing tags)" ---------------------


def test_null_has_no_text():
    assert value_of("null") == ""


def test_null_element_is_not_self_closing():
    assert out(run("/root/v", stdin=json_doc("null"))) == '<v type="null"></v>'


def test_empty_string_element_is_not_self_closing():
    assert out(run("/root/v", stdin=json_doc('""'))) == '<v type="str"></v>'


def test_empty_object_element_is_not_self_closing():
    assert out(run("/root/v", stdin=json_doc("{}"))) == '<v type="dict"></v>'


def test_empty_array_element_is_not_self_closing():
    assert out(run("/root/v", stdin=json_doc("[]"))) == '<v type="list"></v>'


# --- Contract: "Every converted element except `<root>` carries `type` in: -
# --- `str`, `int`, `float`, `bool`, `dict`, `list`, `null`." ---------------


def test_string_value_is_typed_str():
    assert type_of('"widget"') == "str"


def test_integer_value_is_typed_int():
    assert type_of("2") == "int"


def test_float_value_is_typed_float():
    assert type_of("1.5") == "float"


def test_integral_float_is_still_typed_float():
    # The text loses the fraction, the type does not.
    assert type_of("1.0") == "float"


def test_boolean_value_is_typed_bool():
    assert type_of("true") == "bool"


def test_object_value_is_typed_dict():
    assert type_of('{"a": 1}') == "dict"


def test_array_value_is_typed_list():
    assert type_of("[1]") == "list"


def test_null_value_is_typed_null():
    assert type_of("null") == "null"


def test_array_items_carry_a_type():
    assert out(run("/root/item[1]/@type", stdin=ARRAY)) == "int"


def test_every_converted_element_below_root_carries_a_type():
    doc = b'{"a": {"b": [1, null]}}'
    assert out(run("count(//*[not(self::root)][not(@type)])", stdin=doc)) == "0"


# --- Contract: "Preserve JSON key order in converted XML." -----------------


def test_key_order_follows_the_document_not_sorting():
    doc = b'{"zebra": 1, "apple": 2}'
    assert out(run("name(/root/*[1])", stdin=doc)) == "zebra"


def test_full_conversion_keeps_source_order():
    doc = b'{"b": 1, "a": 2}'
    expected = '<root>\n  <b type="int">1</b>\n  <a type="int">2</a>\n</root>'
    assert out(run("/root", stdin=doc)) == expected


def test_nested_key_order_is_preserved():
    doc = b'{"o": {"z": 1, "a": 2}}'
    assert out(run("name(/root/o/*[1])", stdin=doc)) == "z"


# --- Contract: "JSON keys that are not valid XML element names are invalid -
# --- input and must produce stderr output with exit code `1`." -------------


def test_key_with_a_space_is_rejected():
    result = run("/root", stdin=b'{"my key": 1}')
    assert result.returncode == 1
    assert err(result) != ""


def test_key_starting_with_a_digit_is_rejected():
    assert run("/root", stdin=b'{"1st": 1}').returncode == 1


def test_key_with_markup_characters_is_rejected():
    assert run("/root", stdin=b'{"a<b": 1}').returncode == 1


def test_empty_key_is_rejected():
    assert run("/root", stdin=b'{"": 1}').returncode == 1


def test_nested_invalid_key_is_rejected():
    assert run("/root", stdin=b'{"ok": {"bad key": 1}}').returncode == 1


def test_invalid_key_writes_nothing_to_stdout():
    assert out(run("/root", stdin=b'{"my key": 1}')) == ""


# --- Contract: "(include terms like `json`/`key`/`invalid`)" ---------------


def test_invalid_key_message_mentions_json_key_and_invalid():
    message = err(run("/root", stdin=b'{"my key": 1}')).lower()
    assert "json" in message
    assert "key" in message
    assert "invalid" in message


def test_valid_unusual_keys_are_accepted():
    doc = b'{"_x-1.y": 1}'
    assert out(run("/root/*/text()", stdin=doc)) == "1"
