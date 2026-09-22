"""Interpretation choices for the JSON spec, recorded in AMBIGUITIES.md.

Each section names the ambiguity entry it pins down.
"""

import pytest


# T19: array entries are named `<item>` at every depth, not only at the top
# level.
def test_nested_array_entries_are_items(xjq):
    doc = '{"xs": [1, 2]}'
    assert xjq("count(/root/xs/item)", stdin=doc).stdout == "2\n"
    assert xjq("--text", "/root/xs/item", stdin=doc).stdout == "1\n2\n"


# T19: an array directly inside an array has no key to borrow a name from, so
# its entries are `<item>` as well.
def test_array_inside_array_uses_item(xjq):
    assert xjq("/root/item/item/text()", stdin="[[5]]").stdout == "5\n"


# T20: `type` names the decoded JSON kind, so 1.0 is a float even though it
# renders as "1".
def test_integral_float_keeps_the_float_type(xjq):
    result = xjq("/root", stdin='{"a": 1.0}')
    assert result.stdout == '<root>\n  <a type="float">1</a>\n</root>\n'


# T20: a number written without a fraction is an int.
def test_whole_number_is_an_int(xjq):
    assert xjq("/root/a/@type", stdin='{"a": 1}').stdout == "int\n"


# T21: input that starts like JSON but does not decode falls back to the XML
# parser, so the message is the XML one rather than a JSON syntax error.
def test_undecodable_json_reports_the_xml_error(xjq):
    result = xjq("//a", stdin='{"a": }')
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message
    assert "json" not in message


# T22: minimal form is Python's shortest round-trip repr, so small magnitudes
# keep exponent notation.
def test_small_magnitude_keeps_exponent_notation(xjq):
    assert xjq("/root/a/text()", stdin='{"a": 1e-7}').stdout == "1e-07\n"


# T22: an integral float collapses to its integer form, however large.
def test_large_integral_float_expands_to_an_integer(xjq):
    assert xjq("/root/a/text()", stdin='{"a": 1e30}').stdout == f"{int(1e30)}\n"


# T23: a colon makes a key an unusable XML element name, so it is invalid
# input rather than a namespace-prefixed element.
def test_colon_key_is_invalid(xjq):
    result = xjq("//a", stdin='{"a:b": 1}')
    assert result.returncode == 1
    assert "key" in result.stderr.lower()


# T24: empty containers are documents like any other and convert to a bare
# `<root/>`.
@pytest.mark.parametrize("payload", ["{}", "[]"])
def test_empty_containers_convert_to_an_empty_root(xjq, payload):
    result = xjq("/root", stdin=payload)
    assert result.returncode == 0
    assert result.stdout == "<root/>\n"


# T24: an empty nested container still carries its type.
def test_empty_nested_containers_keep_their_type(xjq):
    doc = '{"d": {}, "l": []}'
    assert xjq("--text", "/root/*/@type", stdin=doc).stdout == "dict\nlist\n"


# T25: duplicate keys decode by the standard rule -- the last one wins and
# only one element is produced.
def test_duplicate_keys_keep_the_last_value(xjq):
    doc = '{"a": 1, "a": 2}'
    assert xjq("count(/root/a)", stdin=doc).stdout == "1\n"
    assert xjq("/root/a/text()", stdin=doc).stdout == "2\n"


# T26: a null element has no text and serializes self-closing, while an empty
# string is text that is merely empty.
def test_null_and_empty_string_serialize_differently(xjq):
    assert xjq("/root/a", stdin='{"a": null}').stdout == '<a type="null"/>\n'
    assert xjq("/root/a", stdin='{"a": ""}').stdout == '<a type="str"></a>\n'
