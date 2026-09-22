"""Spec section: Errors.

Invalid XPath and malformed/empty XML input both exit 1 with a message on
stderr that names the failing stage.
"""

import pytest

from conftest import DOC


# Phrase: "Invalid XPath: stderr message, exit code 1; message should reference `xpath`."
@pytest.mark.parametrize(
    "query",
    [
        "//book[",              # unbalanced predicate
        "//book[@id=]",         # missing operand
        "не xpath",             # not an expression at all
        "//book/bogus-fn()",    # unknown function
        "//ns:book",            # undeclared namespace prefix
    ],
)
def test_invalid_xpath_exits_one_with_xpath_message(xjq, query):
    result = xjq(query, stdin=DOC)
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Phrase: "Invalid XPath: stderr message, exit code 1"
def test_invalid_xpath_writes_nothing_to_stdout(xjq):
    result = xjq("//book[", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr.strip() != ""


# Phrase: "Malformed ... XML input: stderr message, exit code 1;
#          message should reference `xml`/`parse`."
@pytest.mark.parametrize(
    "payload",
    [
        "<library><book></library>",      # mismatched end tag
        "<library><book>",                # unclosed tags
        "not xml at all",                 # plain text
        "<library><<>>",                  # garbage markup
        "<a>&undefined;</a>",             # undefined entity
    ],
)
def test_malformed_xml_exits_one_with_parse_message(xjq, payload):
    result = xjq("//book", stdin=payload)
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message


# Phrase: "Malformed/empty XML input: stderr message, exit code 1"
@pytest.mark.parametrize("payload", ["", "   \n\t  "])
def test_empty_xml_input_exits_one_with_parse_message(xjq, payload):
    result = xjq("//book", stdin=payload)
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message


# Phrase: "Malformed/empty XML input: ... exit code 1"
def test_malformed_input_writes_nothing_to_stdout(xjq):
    result = xjq("//book", stdin="<library><book></library>")
    assert result.stdout == ""
