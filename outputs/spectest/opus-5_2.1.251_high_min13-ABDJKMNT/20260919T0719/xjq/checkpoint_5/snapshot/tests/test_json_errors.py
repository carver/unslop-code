"""Spec section: JSON-to-XML Contract, invalid keys.

A JSON key that cannot be an XML element name makes the whole input invalid.
"""

import pytest

from conftest import JSON_OBJECT

# Keys rejected by the XML Name production: a space, a leading digit, a leading
# punctuation mark, a namespace colon, and the empty key.
INVALID_KEYS = ["a b", "1a", "-a", ".a", "a:b", "", "a/b", "#tag", "a,b"]


# Phrase: "JSON keys that are not valid XML element names are invalid input and
# must produce stderr output with exit code `1`".
@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_key_exits_one(xjq, key):
    result = xjq("//a", stdin='{"%s": 1}' % key)
    assert result.returncode == 1
    assert result.stderr.strip() != ""


# Phrase: "... (include terms like `json`/`key`/`invalid`)".
@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_key_message_names_the_problem(xjq, key):
    message = xjq("//a", stdin='{"%s": 1}' % key).stderr.lower()
    assert "json" in message and "key" in message and "invalid" in message


# Phrase: "... are invalid input" -- nothing is written to stdout.
def test_invalid_key_writes_nothing_to_stdout(xjq):
    assert xjq("//a", stdin='{"a b": 1}').stdout == ""


# Phrase: "JSON keys that are not valid XML element names are invalid input"
# -- a key nested anywhere in the document counts.
def test_invalid_nested_key_is_rejected(xjq):
    result = xjq("//a", stdin='{"ok": {"not ok": 1}}')
    assert result.returncode == 1
    assert "key" in result.stderr.lower()


# Phrase: "JSON keys that are not valid XML element names" -- a key inside an
# object held by an array counts too.
def test_invalid_key_inside_array_entry_is_rejected(xjq):
    result = xjq("//a", stdin='[{"bad key": 1}]')
    assert result.returncode == 1
    assert "key" in result.stderr.lower()


# Phrase: "JSON keys that are not valid XML element names" -- keys that are
# valid names stay valid, including underscores, dots, dashes and non-ASCII.
@pytest.mark.parametrize("key", ["_private", "a.b", "a-b", "x1", "naïve", "_"])
def test_valid_keys_are_accepted(xjq, key):
    result = xjq("count(//*)", stdin='{"%s": 1}' % key)
    assert result.returncode == 0
    assert result.stdout == "2\n"


# Phrase: invalid keys are an input problem, so they are reported the way the
# other input failures are -- before the query is even considered.
def test_invalid_key_is_reported_before_query_errors(xjq):
    message = xjq("//book[", stdin='{"a b": 1}').stderr.lower()
    assert "json" in message
    assert "xpath" not in message


# Phrase: string *values* are unconstrained; only keys must be XML names.
def test_values_may_contain_anything(xjq):
    assert xjq("/root/a/text()", stdin='{"a": "1 < 2 & true"}').stdout == "1 < 2 & true\n"


# Phrase: a valid document is not affected by the key check.
def test_valid_document_is_not_rejected(xjq):
    assert xjq("//title/text()", stdin=JSON_OBJECT).returncode == 0
