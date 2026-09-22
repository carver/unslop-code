#!/usr/bin/env python3
"""xjq -- query XML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Reads an XML (or HTML) document from stdin, evaluates QUERY against it and
prints the results.  Text and attribute results are whitespace-normalised and
printed one per line; node results are pretty-printed as XML.
"""

import argparse
import copy
import io
import re
import sys

from lxml import etree

WHITESPACE = re.compile(r"\s+")

HTML_HINT = re.compile(rb"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]", re.I)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML from stdin using an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; input is always read from stdin",
    )
    return parser


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def read_stdin():
    try:
        data = sys.stdin.buffer.read()
    except AttributeError:  # pragma: no cover - stdin replaced by a text stream
        data = sys.stdin.read().encode("utf-8", "replace")
    except Exception as exc:
        die("xjq: error: could not read xml input from stdin: %s" % exc)
    return data


def parse_document(data):
    """Parse the input, raising a friendly error for malformed/empty input."""
    if not data or not data.strip():
        die("xjq: error: failed to parse xml input: the document is empty")

    xml_parser = etree.XMLParser(
        remove_blank_text=True,
        resolve_entities=False,
        no_network=True,
        recover=False,
    )
    try:
        return etree.parse(io.BytesIO(data), xml_parser)
    except etree.XMLSyntaxError as xml_error:
        if HTML_HINT.search(data[:4096]):
            tree = parse_html(data)
            if tree is not None:
                return tree
        die("xjq: error: failed to parse xml input: %s" % xml_error)


def parse_html(data):
    html_parser = etree.HTMLParser(remove_blank_text=True, no_network=True)
    try:
        tree = etree.parse(io.BytesIO(data), html_parser)
    except etree.XMLSyntaxError:
        return None
    return tree if tree is not None and tree.getroot() is not None else None


def namespaces(tree):
    root = tree.getroot()
    nsmap = getattr(root, "nsmap", None) or {}
    return {prefix: uri for prefix, uri in nsmap.items() if prefix}


def evaluate(tree, query):
    if query.strip() == "/":
        # lxml returns an empty node-set for the bare document node.
        return [tree]
    try:
        return tree.xpath(query, namespaces=namespaces(tree), smart_strings=True)
    except etree.XPathError as exc:
        die("xjq: error: invalid xpath expression %r: %s" % (query, exc))
    except (TypeError, ValueError) as exc:
        die("xjq: error: invalid xpath expression %r: %s" % (query, exc))


def normalize(text):
    return WHITESPACE.sub(" ", text).strip()


def scalar_to_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value in (float("inf"), float("-inf")):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def serialize_node(node):
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
    node = copy.deepcopy(node)
    node.tail = None
    try:
        text = etree.tostring(node, pretty_print=True, encoding="unicode")
    except (TypeError, ValueError):
        text = etree.tostring(node, pretty_print=True).decode("utf-8", "replace")
    return text.rstrip("\n")


def write(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:  # pragma: no cover
        pass


def render(result):
    """Turn an lxml XPath result into the text to write to stdout."""
    if result is None:
        return ""

    if not isinstance(result, list):
        if isinstance(result, (str, bytes)):
            line = normalize(scalar_to_text(result))
            return line + "\n" if line else ""
        return scalar_to_text(result) + "\n"

    if not result:
        return ""

    nodes = [
        item
        for item in result
        if isinstance(item, (etree._Element, etree._ElementTree))
        and not isinstance(item, str)
    ]
    if nodes:
        return serialize_node(nodes[0]) + "\n"

    lines = [normalize(scalar_to_text(item)) for item in result]
    if not any(lines):
        return ""
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Tolerate (and ignore) any unrecognised option flags.
    args, _unknown = build_parser().parse_known_args(argv)

    data = read_stdin()
    tree = parse_document(data)
    result = evaluate(tree, args.query)
    write(render(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BrokenPipeError:  # pragma: no cover
        sys.exit(0)
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)
