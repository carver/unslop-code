#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import copy
import math
import sys

from lxml import etree

PROG = "xjq.py"


def _fail(message):
    """Report an error on stderr and exit with status 1."""
    sys.stderr.write("{}: error: {}\n".format(PROG, message))
    sys.stderr.flush()
    raise SystemExit(1)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML read from stdin using an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility but not used; input is always stdin",
    )
    return parser.parse_args(argv)


def read_stdin():
    """Read the whole document from stdin as bytes, so lxml can honour the
    document's own encoding declaration."""
    try:
        data = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        data = sys.stdin.read().encode("utf-8", "replace")
    except OSError as exc:
        _fail("failed to read xml input from stdin: {}".format(exc))
    return data


def parse_document(data):
    """Parse `data` as XML with case-sensitive element matching."""
    if not data.strip():
        _fail("failed to parse xml input: empty xml document")

    parser = etree.XMLParser(recover=False, resolve_entities=True)
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        _fail("failed to parse xml input: {}".format(exc))
    except ValueError as exc:
        _fail("failed to parse xml input: {}".format(exc))

    if root is None:
        _fail("failed to parse xml input: no root element found")
    return root.getroottree()


def evaluate(tree, query):
    """Evaluate an XPath 1.0 expression against the parsed document."""
    try:
        return tree.xpath(query)
    except (etree.XPathError, etree.LxmlError) as exc:
        _fail("invalid xpath expression: {}".format(exc))
    except (ValueError, TypeError) as exc:
        _fail("invalid xpath expression: {}".format(exc))


def normalize(text):
    """Strip a result and collapse internal whitespace runs to single spaces."""
    return " ".join(text.split())


def format_number(value):
    """Render a number using XPath 1.0 string() conventions."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value):
        return str(int(value))
    return repr(value)


def to_text(value):
    """Render one non-node result as text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _drop_ignorable_whitespace(element):
    """Remove whitespace-only text and tails so pretty-printing can re-indent."""
    for node in element.iter():
        if isinstance(node.tag, str) and node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None


def serialize_node(node):
    """Pretty-print a single node as XML."""
    clone = copy.deepcopy(node)
    clone.tail = None
    _drop_ignorable_whitespace(clone)
    return etree.tostring(
        clone, pretty_print=True, encoding="unicode", with_tail=False
    )


def render(result):
    """Turn an XPath result into the bytes to write to stdout."""
    if not isinstance(result, list):
        result = [result]

    if not result:
        return b""

    nodes = [item for item in result if isinstance(item, etree._Element)]
    if nodes:
        # Only the first node is emitted when several match.
        return serialize_node(nodes[0]).encode("utf-8")

    lines = [normalize(to_text(item)) for item in result]
    return "\n".join(lines).encode("utf-8")


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    data = read_stdin()
    tree = parse_document(data)
    result = evaluate(tree, args.query)

    payload = render(result)
    if payload:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
