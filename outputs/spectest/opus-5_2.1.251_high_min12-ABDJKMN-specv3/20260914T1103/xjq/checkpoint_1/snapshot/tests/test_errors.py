"""Spec section: Errors.

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


# --- Phrase: "Invalid XPath: stderr message, exit code `1`" ---------------
# Context: a query that is not a valid XPath 1.0 expression.

@pytest.mark.parametrize(
    "query",
    [
        "//[",
        "///",
        "//a[",
        "//a[@x=",
        "not valid at all !!",
        "//a/..//)",
        "",
    ],
)
def test_invalid_xpath_exits_one(xjq, query, books):
    r = xjq(query, stdin=books)
    assert r.returncode == 1


def test_invalid_xpath_writes_to_stderr(xjq, books):
    r = xjq("//[", stdin=books)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_invalid_xpath_writes_nothing_to_stdout(xjq, books):
    r = xjq("//[", stdin=books)
    assert r.stdout == ""


def test_unknown_xpath_function_is_an_xpath_error(xjq, books):
    r = xjq("no_such_function(//book)", stdin=books)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


def test_unknown_namespace_prefix_is_an_xpath_error(xjq, books):
    r = xjq("//ns:book", stdin=books)
    assert r.returncode == 1
    assert "xpath" in r.stderr.lower()


# --- Phrase: "message should reference `xpath`" ---------------------------
# Context: the stderr text names xpath (case-insensitively).

@pytest.mark.parametrize("query", ["//[", "//a[@x=", "not valid at all !!"])
def test_invalid_xpath_message_mentions_xpath(xjq, query, books):
    r = xjq(query, stdin=books)
    assert "xpath" in r.stderr.lower()


# --- Phrase: "Malformed/empty XML input: ... exit code `1`" (malformed) ---
# Context: stdin that is not parseable as a document.

@pytest.mark.parametrize(
    "document",
    [
        "<a><b></a>",
        "<a><unclosed>",
        "this is not xml at all",
        "<<<>>>",
        "<a>&nosuchentity;</a>",
        "<a></b>",
    ],
)
def test_malformed_xml_exits_one(xjq, document):
    r = xjq("//a", stdin=document)
    assert r.returncode == 1


def test_malformed_xml_writes_to_stderr(xjq):
    r = xjq("//a", stdin="<a><b></a>")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_malformed_xml_writes_nothing_to_stdout(xjq):
    r = xjq("//a", stdin="<a><b></a>")
    assert r.stdout == ""


# --- Phrase: "Malformed/empty XML input: ... exit code `1`" (empty) -------
# Context: no input, or input that is only whitespace.

def test_empty_stdin_exits_one(xjq):
    r = xjq("//a", stdin="")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_whitespace_only_stdin_exits_one(xjq):
    r = xjq("//a", stdin="   \n\t\n  ")
    assert r.returncode == 1
    assert r.stderr.strip() != ""


def test_declaration_only_stdin_exits_one(xjq):
    r = xjq("//a", stdin='<?xml version="1.0" encoding="UTF-8"?>')
    assert r.returncode == 1


# --- Phrase: "message should reference `xml`/`parse`" ---------------------
# Context: the stderr text names xml or parse (case-insensitively).

@pytest.mark.parametrize(
    "document", ["<a><b></a>", "not xml at all", "", "   \n  ", "<a><unclosed>"]
)
def test_xml_error_message_mentions_xml_or_parse(xjq, document):
    r = xjq("//a", stdin=document)
    assert r.returncode == 1
    lowered = r.stderr.lower()
    assert "xml" in lowered or "parse" in lowered


# --- Phrase: error precedence (both error conditions at once) -------------
# Context: not stated by the spec; input is read and parsed before the query
# is evaluated, so a bad document reports the xml/parse error.

def test_bad_document_and_bad_query_reports_one_error_and_exits_one(xjq):
    r = xjq("//[", stdin="not xml at all")
    assert r.returncode == 1
    assert r.stderr.strip() != ""
    assert r.stdout == ""


# --- Phrase: "stderr message" (no traceback) ------------------------------
# Context: errors are reported as messages, not uncaught exceptions.

def test_xpath_error_is_not_a_traceback(xjq, books):
    r = xjq("//[", stdin=books)
    assert "Traceback" not in r.stderr


def test_xml_error_is_not_a_traceback(xjq):
    r = xjq("//a", stdin="<a><b></a>")
    assert "Traceback" not in r.stderr


def test_error_message_is_a_single_line(xjq, books):
    r = xjq("//[", stdin=books)
    assert len(r.stderr.strip().splitlines()) == 1
