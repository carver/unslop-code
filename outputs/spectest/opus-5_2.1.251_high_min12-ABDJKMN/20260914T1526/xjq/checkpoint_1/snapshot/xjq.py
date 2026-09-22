#!/usr/bin/env python3
"""xjq.py -- query XML/HTML read from stdin with an XPath 1.0 expression.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

QUERY is an XPath 1.0 expression; INFILE is accepted but ignored -- the
document is always read from stdin.
"""
import argparse
import copy
import math
import re
import sys

from lxml import etree

WHITESPACE = re.compile(r"\s+")

# A document that announces itself as HTML may be parsed with the recovering
# HTML parser when it is not well-formed XML (see AMBIGUITIES.md, T2).
HTML_PROLOGUE = re.compile(
    rb"\A\s*(?:<\?[^>]*\?>\s*|<!--.*?-->\s*)*<\s*(?:!doctype\s+html\b|html\b)",
    re.IGNORECASE | re.DOTALL,
)


def die(message):
    """Report an error on stderr and exit with status 1."""
    sys.stderr.write("error: %s\n" % message)
    sys.exit(1)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML/HTML from stdin with an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility but ignored; input is read from stdin",
    )
    return parser.parse_args(argv)


def read_stdin():
    source = getattr(sys.stdin, "buffer", None)
    if source is None:
        return sys.stdin.read().encode("utf-8", "replace")
    return source.read()


def parse_document(data):
    """Parse the input bytes, or exit 1 with a message mentioning xml/parse."""
    if not data.strip():
        die("failed to parse xml input: no element found (empty input)")

    try:
        return etree.fromstring(data, etree.XMLParser(resolve_entities=False))
    except etree.XMLSyntaxError as exc:
        xml_error = exc

    if HTML_PROLOGUE.match(data):
        try:
            root = etree.fromstring(data, etree.HTMLParser())
        except (etree.XMLSyntaxError, etree.ParserError):
            root = None
        if root is not None and (len(root) or (root.text or "").strip()):
            return root

    die("failed to parse xml input: %s" % first_line(xml_error))


def first_line(exc):
    text = str(exc).strip().splitlines()
    return text[0] if text else exc.__class__.__name__


def evaluate(root, query):
    """Evaluate the XPath, or exit 1 with a message mentioning xpath."""
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        die("invalid xpath expression %r: %s" % (query, first_line(exc)))
    except (TypeError, ValueError) as exc:  # e.g. non-string query internals
        die("invalid xpath expression %r: %s" % (query, first_line(exc)))


def collapse(value):
    """Strip a result and collapse internal whitespace runs to single spaces."""
    return WHITESPACE.sub(" ", value).strip()


def format_number(value):
    """XPath 1.0 string-conversion for numbers."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value):
        return str(int(value))
    return repr(value)


def format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def is_node(value):
    """True for results that should be serialized as XML rather than text."""
    return isinstance(value, etree._Element)


def serialize_node(node):
    """Pretty-print a single node, without its tail text."""
    node = copy.deepcopy(node)
    node.tail = None
    text = etree.tostring(node, pretty_print=True)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return text.rstrip("\n")


def render(result):
    """Turn an XPath result into the text to write to stdout, or None."""
    if isinstance(result, list):
        if not result:
            return None
        if is_node(result[0]):
            # Only the first node is emitted when several nodes match.
            return serialize_node(result[0])
        return "\n".join(collapse(format_scalar(item)) for item in result)

    if is_node(result):
        return serialize_node(result)

    return collapse(format_scalar(result))


def main(argv=None):
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    root = parse_document(read_stdin())
    output = render(evaluate(root, args.query))
    if output is not None:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
