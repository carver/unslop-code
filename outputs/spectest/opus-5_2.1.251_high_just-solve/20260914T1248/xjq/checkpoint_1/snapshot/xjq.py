#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Input is always read from stdin; INFILE is accepted but ignored.
"""

import argparse
import copy
import re
import sys

from lxml import etree

PROG = "xjq"

# Heuristic markers that mean "this is really an HTML document", used to decide
# whether a strict-XML failure should be retried with the HTML parser.
_HTML_HINT = re.compile(
    rb"<!DOCTYPE\s+html|<html[\s>]|<HTML[\s>]|<body[\s>]|<BODY[\s>]", re.IGNORECASE
)

_WS = re.compile(r"\s+")


def die(message, code=1):
    sys.stderr.write("%s: %s\n" % (PROG, message))
    sys.exit(code)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Evaluate an XPath 1.0 query against XML/HTML read from stdin.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; input is always read from stdin",
    )
    # Unknown options are ignored rather than fatal: the interface promises
    # OPTIONS but assigns no meaning to them.
    args, _unknown = parser.parse_known_args(argv)
    return args


def read_input():
    try:
        data = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        data = sys.stdin.read().encode("utf-8", "replace")
    if not data or not data.strip():
        die("failed to parse xml input: empty input")
    return data


def parse_document(data):
    """Parse as XML; retry as HTML only for documents that really look like HTML."""
    xml_parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
    try:
        return etree.fromstring(data, xml_parser)
    except etree.XMLSyntaxError as xml_error:
        if not _HTML_HINT.search(data):
            die("failed to parse xml input: %s" % xml_error)

    html_parser = etree.HTMLParser(recover=True, remove_blank_text=False)
    try:
        root = etree.fromstring(data, html_parser)
    except etree.LxmlError as html_error:
        die("failed to parse xml input: %s" % html_error)
    if root is None:
        die("failed to parse xml input: no document element found")
    return root


def namespaces_for(root):
    """Expose the document's own prefixes so prefixed queries just work."""
    prefixes = {}
    try:
        for element in root.iter():
            nsmap = getattr(element, "nsmap", None)
            if not nsmap:
                continue
            for prefix, uri in nsmap.items():
                if prefix and uri and prefix not in prefixes:
                    prefixes[prefix] = uri
    except Exception:
        return {}
    return prefixes


def evaluate(root, query, namespaces):
    try:
        return root.xpath(query, namespaces=namespaces) if namespaces else root.xpath(query)
    except etree.XPathError as error:
        die("invalid xpath expression %r: %s" % (query, error))
    except (TypeError, ValueError) as error:
        die("invalid xpath expression %r: %s" % (query, error))


def normalize(text):
    return _WS.sub(" ", text).strip()


def format_number(value):
    if value != value:  # NaN
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "Infinity" if value > 0 else "-Infinity"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def is_xml_node(item):
    return isinstance(item, etree._Element) or isinstance(item, etree._ElementTree)


def pretty_print(node):
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
    node = copy.deepcopy(node)
    node.tail = None

    raw = etree.tostring(node)
    try:
        cleaner = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
        reparsed = etree.fromstring(raw, cleaner)
        text = etree.tostring(reparsed, pretty_print=True, encoding="unicode")
    except etree.LxmlError:
        text = etree.tostring(node, pretty_print=True, encoding="unicode")
    return text.rstrip("\n")


def node_to_text(item):
    """Best-effort string-value of a node, matching XPath string() semantics."""
    if isinstance(item, etree._ElementTree):
        item = item.getroot()
    if isinstance(item, etree._Element):
        return "".join(item.itertext())
    return str(item)


def render(result):
    """Turn an XPath result into the text to print (or None for no output)."""
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, float) or isinstance(result, int):
        return format_number(float(result))
    if isinstance(result, (str, bytes)):
        if isinstance(result, bytes):
            result = result.decode("utf-8", "replace")
        text = normalize(result)
        return text or None

    if not isinstance(result, list):
        text = normalize(str(result))
        return text or None

    if not result:
        return None

    nodes = [item for item in result if is_xml_node(item)]
    if nodes:
        # Serialized XML output: only the first matching node.
        return pretty_print(nodes[0])

    lines = []
    for item in result:
        if isinstance(item, bytes):
            item = item.decode("utf-8", "replace")
        elif not isinstance(item, str):
            item = node_to_text(item)
        text = normalize(item)
        if text:
            lines.append(text)
    if not lines:
        return None
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    data = read_input()
    root = parse_document(data)
    result = evaluate(root, args.query, namespaces_for(root))
    output = render(result)
    if output:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
