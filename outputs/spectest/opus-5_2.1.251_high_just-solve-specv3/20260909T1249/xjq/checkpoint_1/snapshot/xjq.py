#!/usr/bin/env python3
"""xjq - query XML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import re
import sys

from lxml import etree

_WS = re.compile(r"\s+")
_LOOKS_LIKE_HTML = re.compile(rb"<!doctype\s+html|<html[\s>]", re.IGNORECASE)


def die(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def normalize(text):
    """Strip, then collapse internal whitespace runs to a single space."""
    return _WS.sub(" ", text.strip())


def read_stdin():
    data = sys.stdin.buffer.read()
    if isinstance(data, str):  # pragma: no cover - defensive
        data = data.encode("utf-8")
    return data


def parse_document(data):
    """Parse XML case-sensitively; fall back to HTML only for HTML documents."""
    if not data.strip():
        die("xjq: error: could not parse xml input: input is empty")

    try:
        parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        xml_error = exc

    if _LOOKS_LIKE_HTML.search(data):
        try:
            html_parser = etree.HTMLParser(recover=True)
            root = etree.fromstring(data, html_parser)
            if root is not None and len(root) or (root is not None and root.text):
                return root
        except etree.XMLSyntaxError:
            pass

    die("xjq: error: failed to parse xml input: %s" % xml_error)


def compile_and_run(root, query):
    nsmap = {p: u for p, u in (root.nsmap or {}).items() if p}
    try:
        xpath = etree.XPath(query, namespaces=nsmap or None, smart_strings=True)
    except (etree.XPathSyntaxError, etree.XPathError, ValueError) as exc:
        die("xjq: error: invalid xpath expression %r: %s" % (query, exc))

    try:
        return xpath(root.getroottree())
    except (etree.XPathEvalError, etree.XPathError) as exc:
        die("xjq: error: invalid xpath expression %r: %s" % (query, exc))


def pretty_xml(node):
    """Serialize a node as pretty-printed XML."""
    try:
        raw = etree.tostring(node, encoding="unicode", with_tail=False)
    except Exception:  # pragma: no cover - defensive
        return None

    if isinstance(node.tag, str):
        try:
            parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
            reparsed = etree.fromstring(raw.encode("utf-8"), parser)
            return etree.tostring(
                reparsed, encoding="unicode", pretty_print=True, with_tail=False
            ).rstrip("\n")
        except etree.XMLSyntaxError:
            pass

    return etree.tostring(
        node, encoding="unicode", pretty_print=True, with_tail=False
    ).rstrip("\n")


def format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value in (float("inf"), float("-inf")):
            return "Infinity" if value > 0 else "-Infinity"
        if value == int(value):
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def render(result):
    """Return (text, is_xml); text is None when there is nothing to output."""
    if result is None:
        return None, False

    if not isinstance(result, list):
        if isinstance(result, (str, bytes)):
            text = normalize(format_scalar(result))
            return (text or None), False
        return format_scalar(result), False

    if not result:
        return None, False

    # An XML node result: emit only the first matching node, pretty-printed.
    for item in result:
        if isinstance(item, (etree._Element, etree._ElementTree)):
            node = item.getroot() if isinstance(item, etree._ElementTree) else item
            return pretty_xml(node), True

    lines = [normalize(format_scalar(item)) for item in result]
    return "\n".join(lines), False


def build_parser():
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML read from stdin using an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; input is always read from stdin",
    )
    parser.add_argument(
        "-v", "--version", action="version", version="xjq 1.0",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    data = read_stdin()
    root = parse_document(data)
    result = compile_and_run(root, args.query)

    output, is_xml = render(result)
    if output:
        sys.stdout.write(output)
        if is_xml:
            sys.stdout.write("\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # pragma: no cover
        sys.exit(0)
