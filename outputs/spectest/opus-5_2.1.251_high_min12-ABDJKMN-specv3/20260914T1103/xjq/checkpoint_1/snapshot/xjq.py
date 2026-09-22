#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import copy
import math
import re
import sys

from lxml import etree

WHITESPACE_RUN = re.compile(r"\s+")
HTML_MARKER = re.compile(rb"<!DOCTYPE\s+html|<html[\s>]", re.IGNORECASE)
INDENT = "  "


class XMLInputError(Exception):
    """stdin could not be parsed as an XML/HTML document."""


class QueryError(Exception):
    """QUERY is not a usable XPath 1.0 expression."""


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        usage="%(prog)s [OPTIONS] QUERY [INFILE]",
        description="Evaluate an XPath 1.0 QUERY against XML/HTML read from stdin.",
    )
    parser.add_argument("QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility but not used; input is read from stdin",
    )
    return parser.parse_args(argv)


def parse_document(data):
    """Parse `data` (bytes) as XML, falling back to HTML for HTML documents.

    Element names keep their case in both paths for the names a query can
    reach: the XML parser never folds case, and the HTML fallback only runs
    for documents that announce themselves as HTML.
    """
    if not data.strip():
        raise XMLInputError("empty xml input: nothing to parse")

    try:
        root = etree.fromstring(data, etree.XMLParser())
    except etree.XMLSyntaxError as exc:
        if not HTML_MARKER.search(data):
            raise XMLInputError("could not parse xml input: %s" % _first_line(exc))
        try:
            root = etree.fromstring(data, etree.HTMLParser())
        except etree.XMLSyntaxError as html_exc:
            raise XMLInputError(
                "could not parse xml input: %s" % _first_line(html_exc)
            )

    if root is None:
        raise XMLInputError("could not parse xml input: no document element found")
    return root


def evaluate(root, query):
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        raise QueryError("invalid xpath expression %r: %s" % (query, _first_line(exc)))
    except (ValueError, TypeError) as exc:
        raise QueryError("invalid xpath expression %r: %s" % (query, _first_line(exc)))


def clean(text):
    """Strip a result and collapse its internal whitespace runs."""
    return WHITESPACE_RUN.sub(" ", text).strip()


def is_node(value):
    return isinstance(value, etree._Element)


def serialize_node(node):
    """Pretty-print a single node, re-indenting whitespace-only text."""
    node = copy.deepcopy(node)
    node.tail = None
    try:
        etree.indent(node, space=INDENT)
    except (AttributeError, TypeError, ValueError):
        pass
    xml = etree.tostring(node, pretty_print=True, with_tail=False)
    return xml.decode("utf-8").rstrip("\n")


def format_number(number):
    """XPath 1.0 string-value of a number."""
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    if number == int(number):
        return str(int(number))
    return repr(number)


def scalar_text(value):
    """XPath 1.0 string-value of a non-node result."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return format_number(float(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if is_node(value):
        return "".join(value.itertext())
    return str(value)


def render(result):
    """Turn an XPath result into the bytes-ready text to print, or None."""
    if not isinstance(result, list):
        result = [result]
    if not result:
        return None

    if is_node(result[0]):
        return serialize_node(result[0])

    lines = [line for line in (clean(scalar_text(r)) for r in result) if line]
    if not lines:
        return None
    return "\n".join(lines)


def _first_line(exc):
    message = str(exc).strip().splitlines()
    return message[0] if message else exc.__class__.__name__


def fail(message):
    sys.stderr.write("xjq.py: error: %s\n" % message)
    return 1


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    data = sys.stdin.buffer.read()

    try:
        root = parse_document(data)
    except XMLInputError as exc:
        return fail(str(exc))

    try:
        result = evaluate(root, args.QUERY)
    except QueryError as exc:
        return fail(str(exc))

    output = render(result)
    if output:
        sys.stdout.buffer.write(output.encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
