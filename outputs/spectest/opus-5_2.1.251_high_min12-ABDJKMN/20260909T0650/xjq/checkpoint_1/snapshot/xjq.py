#!/usr/bin/env python3
"""xjq -- XPath querying of XML read from stdin.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

QUERY is an XPath 1.0 expression. INFILE is accepted for compatibility but is
never read: the document always comes from stdin.
"""

import argparse
import copy
import math
import re
import sys

from lxml import etree

PROG = "xjq.py"

EXIT_OK = 0
EXIT_ERROR = 1

INDENT = "  "

_WHITESPACE_RUN = re.compile(r"\s+")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML read from stdin with an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; ignored (input is read from stdin)",
    )
    return parser.parse_args(argv)


def read_stdin():
    """Read the whole document from stdin as bytes."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read()
    return sys.stdin.read().encode("utf-8", "replace")


def parse_document(data):
    """Parse `data` as XML with case-sensitive, non-recovering parsing.

    Element and attribute names keep the case they were written with, and
    anything that is not well formed (including empty input) raises.
    """
    parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
    return etree.fromstring(data, parser)


def compile_query(query):
    return etree.XPath(query)


def is_node(value):
    """True for results lxml represents as nodes (elements, comments, PIs)."""
    return isinstance(value, (etree._Element, etree._ElementTree))


def format_number(value):
    """XPath 1.0 string() conversion for a number."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value):
        return str(int(value))
    return repr(float(value))


def to_text(value):
    """Render a non-node XPath result as its string value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return format_number(float(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def normalize(text):
    """Strip, then collapse internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def serialize_node(node):
    """Pretty-print a single node as XML."""
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
        if node is None:
            return ""
    node = copy.deepcopy(node)
    node.tail = None
    try:
        etree.indent(node, space=INDENT)
    except (TypeError, ValueError):
        pass
    return etree.tostring(
        node, pretty_print=True, with_tail=False, encoding="unicode"
    )


def render(result):
    """Turn an XPath result into the exact text to write to stdout."""
    if isinstance(result, list):
        if not result:
            return ""
        if is_node(result[0]):
            # Multiple XML nodes: only the first one is emitted.
            return serialize_node(result[0])
        lines = [normalize(to_text(item)) for item in result]
        return "".join(line + "\n" for line in lines)

    if is_node(result):
        return serialize_node(result)
    return normalize(to_text(result)) + "\n"


def fail(message):
    sys.stderr.write("%s: error: %s\n" % (PROG, message))
    return EXIT_ERROR


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        query = compile_query(args.query)
    except etree.XPathError as exc:
        return fail("invalid xpath expression %r: %s" % (args.query, exc))

    data = read_stdin()

    try:
        root = parse_document(data)
    except etree.XMLSyntaxError as exc:
        return fail("could not parse xml input: %s" % exc)
    except (etree.LxmlError, ValueError) as exc:
        return fail("could not parse xml input: %s" % exc)
    if root is None:
        return fail("could not parse xml input: document is empty")

    try:
        result = query(root)
    except etree.XPathError as exc:
        return fail("invalid xpath expression %r: %s" % (args.query, exc))

    output = render(result)
    if output:
        sys.stdout.write(output)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(EXIT_ERROR)
    except KeyboardInterrupt:
        sys.exit(130)
