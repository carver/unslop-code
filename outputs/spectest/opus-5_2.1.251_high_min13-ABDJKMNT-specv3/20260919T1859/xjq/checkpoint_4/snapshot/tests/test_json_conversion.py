"""The JSON-to-XML contract: element names, text, and ``type`` attributes."""

import json


# Spec: "Wrap converted documents in `<root>`."
def test_object_document_is_wrapped_in_root(run_xjq):
    result = run_xjq("/root", stdin='{"a": 1}')
    assert result.stdout.startswith("<root>")
    assert result.stdout.rstrip("\n").endswith("</root>")


# Spec: "Wrap converted documents in `<root>`." -- an array document is wrapped
# in the same element.
def test_array_document_is_wrapped_in_root(run_xjq):
    assert run_xjq("name(/*)", stdin="[1]").stdout == "root"


# Spec: "`<root>` must not include `type`."
def test_root_has_no_type_attribute(run_xjq):
    assert run_xjq("/root/@type", stdin='{"a": 1}').stdout == ""
    assert run_xjq("count(/root/@*)", stdin="[1]").stdout == "0"
    assert 'type=' not in run_xjq("/root", stdin='{"a": 1}').stdout.splitlines()[0]


# Spec: "For top-level objects: keys become direct child elements."
def test_object_keys_become_direct_children(run_xjq):
    stdin = '{"name": "Ada", "age": 36}'
    assert run_xjq("/root/name/text()", stdin=stdin).stdout == "Ada"
    assert run_xjq("/root/age/text()", stdin=stdin).stdout == "36"
    assert run_xjq("count(/root/*)", stdin=stdin).stdout == "2"


# Spec: "For top-level arrays: each entry becomes an `<item>` child of `<root>`."
def test_array_entries_become_item_children(run_xjq):
    stdin = '["a", "b", "c"]'
    assert run_xjq("/root/item/text()", stdin=stdin).stdout == "a\nb\nc"
    assert run_xjq("count(/root/item)", stdin=stdin).stdout == "3"


# Spec: "For top-level arrays: each entry becomes an `<item>` child of
# `<root>`." -- nested arrays use the same element name. See [T19].
def test_nested_array_entries_also_become_items(run_xjq):
    stdin = '{"tags": ["x", "y"]}'
    assert run_xjq("/root/tags/item/text()", stdin=stdin).stdout == "x\ny"


# Spec: "Object keys become element tag names (case preserved)."
def test_key_case_is_preserved(run_xjq):
    stdin = '{"CamelCase": 1, "lower": 2}'
    assert run_xjq("/root/CamelCase/text()", stdin=stdin).stdout == "1"
    assert run_xjq("/root/camelcase/text()", stdin=stdin).stdout == ""
    assert "<CamelCase" in run_xjq("/root", stdin=stdin).stdout


# Spec: "Object keys become element tag names ..." -- nested objects nest their
# keys as elements.
def test_nested_object_keys_nest_as_elements(run_xjq):
    stdin = json.dumps({"outer": {"inner": {"leaf": "v"}}})
    assert run_xjq("/root/outer/inner/leaf/text()", stdin=stdin).stdout == "v"


# Spec: "Primitive values map to element text: ... booleans as `true`/`false`".
def test_booleans_map_to_true_and_false(run_xjq):
    stdin = '{"yes": true, "no": false}'
    assert run_xjq("/root/yes/text()", stdin=stdin).stdout == "true"
    assert run_xjq("/root/no/text()", stdin=stdin).stdout == "false"


# Spec: "numbers as minimal string form ... `1 -> \"1\"`, `1.0 -> \"1\"`,
# `1.50 -> \"1.5\"`, `0.00012 -> \"0.00012\"`."
def test_numbers_use_minimal_string_form(run_xjq):
    cases = {"1": "1", "1.0": "1", "1.50": "1.5", "0.00012": "0.00012"}
    for literal, expected in cases.items():
        stdin = f'{{"n": {literal}}}'
        assert run_xjq("/root/n/text()", stdin=stdin).stdout == expected, literal


# Spec: "numbers as minimal string form" -- negative and larger values keep the
# shortest round-tripping spelling. See [T21].
def test_more_number_forms(run_xjq):
    cases = {"-2.500": "-2.5", "1e3": "1000", "0": "0", "3.14159": "3.14159"}
    for literal, expected in cases.items():
        stdin = f'{{"n": {literal}}}'
        assert run_xjq("/root/n/text()", stdin=stdin).stdout == expected, literal


# Spec: "null as empty (no self-closing tags)."
def test_null_is_empty_text(run_xjq):
    stdin = '{"nothing": null}'
    assert run_xjq("/root/nothing/text()", stdin=stdin).stdout == ""
    assert run_xjq("count(/root/nothing)", stdin=stdin).stdout == "1"


# Spec: "null as empty (no self-closing tags)." -- the serialized element has a
# separate closing tag.
def test_null_element_is_not_self_closing(run_xjq):
    output = run_xjq("/root/nothing", stdin='{"nothing": null}').stdout
    assert output.rstrip("\n") == '<nothing type="null"></nothing>'


# Spec: "null as empty (no self-closing tags)." -- an empty string, object, and
# array are empty too, and likewise keep a closing tag. See [T23].
def test_other_empty_values_are_not_self_closing(run_xjq):
    expected = {
        '{"a": ""}': '<a type="str"></a>',
        '{"a": {}}': '<a type="dict"></a>',
        '{"a": []}': '<a type="list"></a>',
    }
    for stdin, serialized in expected.items():
        assert run_xjq("/root/a", stdin=stdin).stdout.rstrip("\n") == serialized


# Spec: "Primitive values map to element text" -- strings map to themselves.
def test_strings_map_to_their_own_text(run_xjq):
    assert run_xjq("/root/s/text()", stdin='{"s": "hello"}').stdout == "hello"


# Spec: "Primitive values map to element text" -- markup characters in a string
# are escaped, so the converted document stays well-formed.
def test_string_text_is_escaped(run_xjq):
    stdin = '{"s": "a < b & c"}'
    assert run_xjq("/root/s/text()", stdin=stdin).stdout == "a < b & c"
    assert "&amp;" in run_xjq("/root/s", stdin=stdin).stdout


# Spec: "Every converted element except `<root>` carries `type` in: `str`,
# `int`, `float`, `bool`, `dict`, `list`, `null`."
def test_type_attribute_of_each_json_type(run_xjq):
    stdin = json.dumps(
        {
            "s": "x",
            "i": 1,
            "f": 1.5,
            "b": True,
            "d": {"k": "v"},
            "l": [1],
            "n": None,
        }
    )
    expected = {
        "s": "str",
        "i": "int",
        "f": "float",
        "b": "bool",
        "d": "dict",
        "l": "list",
        "n": "null",
    }
    for key, type_name in expected.items():
        assert run_xjq(f"/root/{key}/@type", stdin=stdin).stdout == type_name, key


# Spec: "Every converted element except `<root>` carries `type` ..." -- a whole
# number written with a fraction is a float, even though its text is `1`.
# See [T20].
def test_integral_float_keeps_the_float_type(run_xjq):
    assert run_xjq("/root/n/@type", stdin='{"n": 1.0}').stdout == "float"
    assert run_xjq("/root/n/text()", stdin='{"n": 1.0}').stdout == "1"
    assert run_xjq("/root/n/@type", stdin='{"n": 1}').stdout == "int"


# Spec: "Every converted element except `<root>` carries `type` ..." -- booleans
# are `bool` rather than `int`.
def test_booleans_are_typed_bool(run_xjq):
    assert run_xjq("/root/b/@type", stdin='{"b": true}').stdout == "bool"


# Spec: "Every converted element except `<root>` carries `type` ..." -- items of
# an array carry it too, each describing its own entry.
def test_array_items_carry_their_own_type(run_xjq):
    result = run_xjq("/root/item/@type", stdin='[1, "a", null, [], {}]')
    assert result.stdout == "int\nstr\nnull\nlist\ndict"


# Spec: "Every converted element except `<root>` carries `type` ..." -- so does
# every element nested below the top level.
def test_nested_elements_carry_type(run_xjq):
    stdin = json.dumps({"outer": [{"inner": 2}]})
    assert run_xjq("/root/outer/item/@type", stdin=stdin).stdout == "dict"
    assert run_xjq("/root/outer/item/inner/@type", stdin=stdin).stdout == "int"


# Spec: "Every converted element except `<root>` carries `type` ..." -- `type`
# is the only attribute a converted element has.
def test_type_is_the_only_attribute(run_xjq):
    assert run_xjq("count(/root/a/@*)", stdin='{"a": 1}').stdout == "1"


# Spec: "Preserve JSON key order in converted XML."
def test_key_order_is_preserved(run_xjq):
    stdin = '{"zebra": 1, "apple": 2, "moose": 3}'
    assert run_xjq("name(/root/*[1])", stdin=stdin).stdout == "zebra"
    assert run_xjq("name(/root/*[2])", stdin=stdin).stdout == "apple"
    assert run_xjq("name(/root/*[3])", stdin=stdin).stdout == "moose"


# Spec: "Preserve JSON key order in converted XML." -- nested objects and array
# entries keep their source order as well.
def test_nested_order_is_preserved(run_xjq):
    stdin = '{"o": {"b": 1, "a": 2}, "l": [3, 1, 2]}'
    assert run_xjq("name(/root/o/*[1])", stdin=stdin).stdout == "b"
    assert run_xjq("/root/l/item/text()", stdin=stdin).stdout == "3\n1\n2"


# Spec: "JSON keys that are not valid XML element names are invalid input and
# must produce stderr output with exit code `1` (include terms like
# `json`/`key`/`invalid`)."
def test_invalid_key_is_an_error(run_xjq):
    result = run_xjq("/root", stdin='{"not a name": 1}')
    assert result.returncode == 1
    assert result.stdout == ""
    message = result.stderr.lower()
    assert "json" in message and "key" in message and "invalid" in message


# Spec: "JSON keys that are not valid XML element names are invalid input ..."
# -- keys starting with a digit, empty keys, and keys with punctuation that XML
# names disallow. See [T22].
def test_invalid_key_forms(run_xjq):
    for key in ["1st", "", "a b", "a/b", "a(b)", "#tag", "a,b", "-lead", ".lead"]:
        stdin = json.dumps({key: 1})
        result = run_xjq("/root", stdin=stdin)
        assert result.returncode == 1, key
        assert result.stderr != "", key


# Spec: "JSON keys that are not valid XML element names are invalid input ..."
# -- names XML does allow are accepted.
def test_valid_key_forms_are_accepted(run_xjq):
    for key in ["a", "_a", "a-b", "a.b", "a1", "Ünicode", "x_1.2-3"]:
        stdin = json.dumps({key: 1})
        result = run_xjq("/root/*[1]/text()", stdin=stdin)
        assert result.returncode == 0, key
        assert result.stdout == "1", key


# Spec: "JSON keys that are not valid XML element names are invalid input ..."
# -- a nested key is checked the same way as a top-level one.
def test_nested_invalid_key_is_an_error(run_xjq):
    result = run_xjq("/root", stdin='{"ok": {"not ok": 1}}')
    assert result.returncode == 1
    assert "json" in result.stderr.lower()


# Spec: "JSON keys that are not valid XML element names are invalid input ..."
# -- the failure is reported as a JSON key problem rather than falling back to
# an XML parse. See [T24].
def test_invalid_key_does_not_fall_back_to_xml(run_xjq):
    result = run_xjq("/root", stdin='{"not a name": 1}')
    assert "json" in result.stderr.lower()
    assert "could not parse xml" not in result.stderr.lower()
