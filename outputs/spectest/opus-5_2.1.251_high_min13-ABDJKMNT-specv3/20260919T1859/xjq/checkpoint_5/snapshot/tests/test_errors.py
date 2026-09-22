"""Error reporting for invalid queries and unparseable input."""

import pytest

from conftest import BOOKS


# Spec: "Invalid XPath: stderr message, exit code `1`; message should reference
# `xpath`."
@pytest.mark.parametrize("query", ["//[", "///", "count(", "//book[", "a//@*['"])
def test_invalid_xpath_exits_one_with_message(run_xjq, query):
    result = run_xjq(query, stdin=BOOKS)
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()
    assert result.stdout == ""


# Spec: "Invalid XPath: ... message should reference `xpath`." -- an undefined
# namespace prefix cannot be evaluated either.
def test_undefined_namespace_prefix_is_an_xpath_error(run_xjq):
    result = run_xjq("//nope:book", stdin=BOOKS)
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Invalid XPath: ... message should reference `xpath`." -- an unknown
# function is a query error, not an input error.
def test_unknown_function_is_an_xpath_error(run_xjq):
    result = run_xjq("no-such-function(//book)", stdin=BOOKS)
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Malformed/empty XML input: stderr message, exit code `1`; message
# should reference `xml`/`parse`."
@pytest.mark.parametrize(
    "document",
    [
        "<a><b></a>",
        "<a>unterminated",
        "not markup at all",
        "<a>&undefined;</a>",
        "<?xml version='1.0'?>",
    ],
)
def test_malformed_xml_exits_one_with_message(run_xjq, document):
    result = run_xjq("//a", stdin=document)
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()
    assert result.stdout == ""


# Spec: "Malformed/empty XML input ..." -- empty stdin.
def test_empty_input_exits_one_with_message(run_xjq):
    result = run_xjq("//a", stdin="")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Spec: "Malformed/empty XML input ..." -- whitespace-only stdin holds no
# document either.
def test_whitespace_only_input_exits_one(run_xjq):
    result = run_xjq("//a", stdin="   \n\t\n")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Spec: "Invalid XPath: stderr message" / "Malformed/empty XML input: stderr
# message" -- diagnostics never leak onto stdout.
def test_errors_keep_stdout_clean(run_xjq):
    assert run_xjq("//[", stdin=BOOKS).stdout == ""
    assert run_xjq("//a", stdin="<a").stdout == ""
