"""Spec section: JSON-to-XML Contract.

The shape of the XML tree that a detected JSON document is converted into.
"""

import pytest

from conftest import JSON_ARRAY, JSON_OBJECT

CONVERTED_OBJECT = """<root>
  <title type="str">Dune</title>
  <year type="int">1965</year>
  <rating type="float">4.5</rating>
  <inPrint type="bool">true</inPrint>
  <sequel type="null"/>
  <author type="dict">
    <first type="str">Frank</first>
    <last type="str">Herbert</last>
  </author>
  <tags type="list">
    <item type="str">scifi</item>
    <item type="str">classic</item>
  </tags>
</root>
"""


# Phrase: "Wrap converted documents in `<root>`."
def test_converted_object_is_wrapped_in_root(xjq):
    assert xjq("name(/*)", stdin=JSON_OBJECT).stdout == "root\n"


# Phrase: "Wrap converted documents in `<root>`." (arrays too)
def test_converted_array_is_wrapped_in_root(xjq):
    assert xjq("name(/*)", stdin=JSON_ARRAY).stdout == "root\n"


# Phrase: the whole contract, on one document.
def test_full_conversion_of_an_object(xjq):
    assert xjq("/root", stdin=JSON_OBJECT).stdout == CONVERTED_OBJECT


# Phrase: "`<root>` must not include `type`."
def test_root_has_no_type_attribute(xjq):
    assert xjq("/root/@type", stdin=JSON_OBJECT).stdout == ""
    assert xjq("count(/root/@*)", stdin=JSON_OBJECT).stdout == "0\n"


# Phrase: "`<root>` must not include `type`." -- visible in the serialization.
def test_serialized_root_opens_without_attributes(xjq):
    assert xjq("/root", stdin='{"a": 1}').stdout.startswith("<root>")


# Phrase: "For top-level objects: keys become direct child elements."
def test_top_level_object_keys_become_children_of_root(xjq):
    doc = '{"a": 1, "b": 2}'
    assert xjq("/root/a/text()", stdin=doc).stdout == "1\n"
    assert xjq("/root/b/text()", stdin=doc).stdout == "2\n"
    assert xjq("count(/root/*)", stdin=doc).stdout == "2\n"


# Phrase: "For top-level arrays: each entry becomes an `<item>` child of
# `<root>`."
def test_top_level_array_entries_become_items(xjq):
    result = xjq("count(/root/item)", stdin=JSON_ARRAY)
    assert result.stdout == "3\n"


# Phrase: "For top-level arrays: each entry becomes an `<item>` child of
# `<root>`." -- entry order is the array's order.
def test_top_level_array_keeps_entry_order(xjq):
    assert xjq("--text", "/root/item", stdin='["a", "b", "c"]').stdout == "a\nb\nc\n"


# Phrase: "Object keys become element tag names (case preserved)."
def test_object_keys_become_tag_names(xjq):
    assert xjq("/root/firstName/text()", stdin='{"firstName": "Ada"}').stdout == "Ada\n"


# Phrase: "Object keys become element tag names (case preserved)."
def test_key_case_is_preserved(xjq):
    doc = '{"Name": "upper", "name": "lower"}'
    assert xjq("/root/Name/text()", stdin=doc).stdout == "upper\n"
    assert xjq("/root/name/text()", stdin=doc).stdout == "lower\n"
    assert xjq("/root/NAME/text()", stdin=doc).stdout == ""


# Phrase: "Primitive values map to element text: booleans as `true`/`false`".
@pytest.mark.parametrize("value,text", [("true", "true"), ("false", "false")])
def test_boolean_text(xjq, value, text):
    assert xjq("/root/a/text()", stdin=f'{{"a": {value}}}').stdout == f"{text}\n"


# Phrase: "Primitive values map to element text: ... numbers as minimal string
# form. Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`,
# `0.00012 -> "0.00012"`."
@pytest.mark.parametrize(
    "value,text",
    [
        ("1", "1"),
        ("1.0", "1"),
        ("1.50", "1.5"),
        ("0.00012", "0.00012"),
        ("-3", "-3"),
        ("0", "0"),
        ("2.75", "2.75"),
    ],
)
def test_number_text_is_minimal(xjq, value, text):
    assert xjq("/root/a/text()", stdin=f'{{"a": {value}}}').stdout == f"{text}\n"


# Phrase: "Primitive values map to element text: ... null as empty."
def test_null_has_no_text(xjq):
    doc = '{"a": null}'
    assert xjq("/root/a/text()", stdin=doc).stdout == ""
    assert xjq("count(/root/a)", stdin=doc).stdout == "1\n"


# Phrase: "Primitive values map to element text" (strings pass through).
def test_string_text_is_the_string(xjq):
    assert xjq("/root/a/text()", stdin='{"a": "hello"}').stdout == "hello\n"


# Phrase: "Every converted element except `<root>` carries `type` in:
# `str`, `int`, `float`, `bool`, `dict`, `list`, `null`."
@pytest.mark.parametrize(
    "value,type_name",
    [
        ('"s"', "str"),
        ("7", "int"),
        ("7.25", "float"),
        ("true", "bool"),
        ("false", "bool"),
        ("{}", "dict"),
        ("[]", "list"),
        ("null", "null"),
    ],
)
def test_every_element_carries_its_type(xjq, value, type_name):
    assert xjq("/root/a/@type", stdin=f'{{"a": {value}}}').stdout == f"{type_name}\n"


# Phrase: "Every converted element except `<root>`" -- including nested ones
# and array items.
def test_nested_elements_carry_type(xjq):
    doc = '{"outer": {"inner": [1]}}'
    assert xjq("/root/outer/@type", stdin=doc).stdout == "dict\n"
    assert xjq("/root/outer/inner/@type", stdin=doc).stdout == "list\n"
    assert xjq("/root/outer/inner/item/@type", stdin=doc).stdout == "int\n"


# Phrase: "Every converted element except `<root>` carries `type`" -- no
# element other than root is missing it.
def test_no_converted_element_lacks_a_type(xjq):
    assert xjq("count(//*[not(@type)])", stdin=JSON_OBJECT).stdout == "1\n"


# Phrase: "Preserve JSON key order in converted XML."
def test_key_order_is_preserved(xjq):
    doc = '{"zebra": 1, "apple": 2, "mango": 3}'
    assert xjq("--text", "/root/*", stdin=doc).stdout == "1\n2\n3\n"
    assert xjq("name(/root/*[1])", stdin=doc).stdout == "zebra\n"
    assert xjq("name(/root/*[3])", stdin=doc).stdout == "mango\n"


# Phrase: "Preserve JSON key order in converted XML." -- nested objects too.
def test_nested_key_order_is_preserved(xjq):
    doc = '{"outer": {"b": 1, "a": 2}}'
    assert xjq("name(/root/outer/*[1])", stdin=doc).stdout == "b\n"
