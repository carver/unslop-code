#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import copy
import math
import re
import sys

from cssselect import GenericTranslator, HTMLTranslator, SelectorError
from lxml import etree

WHITESPACE_RUN = re.compile(r"\s+")
HTML_MARKER = re.compile(rb"<!DOCTYPE\s+html|<html[\s>]", re.IGNORECASE)
INDENT = "  "

# The custom `::text` pseudo-element, only ever valid at the end of a simple
# selector.  The leading whitespace is captured because it is what separates
# the two modes: `a::text` is direct text, `a ::text` is descendant text.
TEXT_PSEUDO = re.compile(r"(?P<ws>\s*)::text\s*$", re.IGNORECASE)
ANY_TEXT_PSEUDO = re.compile(r"::text", re.IGNORECASE)

# Text extraction modes.
DIRECT = "direct"        # one line per element, the element's own text nodes
ALL = "all"              # one line per element, the whole subtree's text
NODES = "nodes"          # one line per descendant text node


class XMLInputError(Exception):
    """stdin could not be parsed as an XML/HTML document."""


class QueryError(Exception):
    """QUERY is not a usable XPath 1.0 expression or CSS selector."""


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        usage="%(prog)s [OPTIONS] QUERY [INFILE]",
        description="Evaluate an XPath 1.0 QUERY against XML/HTML read from stdin.",
    )
    parser.add_argument("QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "--css",
        action="store_true",
        help="interpret QUERY as a CSS selector instead of an XPath expression",
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="extract direct text from matched elements, one per element",
    )
    parser.add_argument(
        "--text-all",
        dest="text_all",
        action="store_true",
        help="extract descendant text from matched elements, one per element",
    )
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

    Returns `(root, is_html)`; `is_html` picks the CSS translator later.
    """
    if not data.strip():
        raise XMLInputError("empty xml input: nothing to parse")

    is_html = False
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
        is_html = True

    if root is None:
        raise XMLInputError("could not parse xml input: no document element found")
    return root, is_html


def split_selector_list(selector):
    """Split a CSS selector list on its top-level commas.

    Commas nested in attribute selectors (`[title=","]`) or functional
    pseudo-classes (`:not(a, b)`) are not separators.
    """
    parts = []
    buf = []
    depth = 0
    quote = None
    escaped = False
    for char in selector:
        if quote:
            buf.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth <= 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(char)
    parts.append("".join(buf))
    return parts


def split_text_pseudo(part, selector):
    """Split one selector-list branch into `(base selector, text mode)`.

    The mode is `DIRECT` for `a::text`, `NODES` for `a ::text`, and `None`
    when the branch carries no `::text` at all.
    """
    match = TEXT_PSEUDO.search(part)
    if match is None:
        if ANY_TEXT_PSEUDO.search(part):
            raise QueryError(
                "invalid css selector %r: ::text must end the selector" % selector
            )
        return part, None

    base = part[: match.start()]
    mode = NODES if match.group("ws") else DIRECT
    if not base.strip():
        # A bare `::text` (or ` ::text`) applies to every element.
        base = "*"
    return base, mode


def compile_css(selector, translator):
    """Translate a CSS selector (possibly using `::text`) into XPath.

    Returns `(xpath, text_mode)`.
    """
    bases = []
    modes = set()
    for part in split_selector_list(selector):
        base, mode = split_text_pseudo(part, selector)
        bases.append(base)
        modes.add(mode)

    if len(modes) > 1:
        raise QueryError(
            "invalid css selector %r: comma-separated selectors must all use "
            "the same ::text mode" % selector
        )

    try:
        xpath = translator.css_to_xpath(", ".join(bases))
    except (SelectorError, ValueError, TypeError) as exc:
        raise QueryError("invalid css selector %r: %s" % (selector, _first_line(exc)))
    return xpath, modes.pop()


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


def is_element(value):
    return is_node(value) and isinstance(value.tag, str)


def extract_text(nodes, mode):
    """Text lines for `nodes` under extraction `mode`.

    `DIRECT` and `ALL` emit one line per element; `NODES` emits one line per
    descendant text node.
    """
    lines = []
    for node in nodes:
        if not is_element(node):
            continue
        if mode == DIRECT:
            lines.append("".join(node.xpath("text()")))
        elif mode == ALL:
            lines.append("".join(node.xpath(".//text()")))
        else:
            lines.extend(node.xpath(".//text()"))
    return lines


def render(result, text_mode=None):
    """Turn an XPath result into the bytes-ready text to print, or None."""
    if not isinstance(result, list):
        result = [result]
    if not result:
        return None

    if text_mode and is_element(result[0]):
        # Text extraction replaces the XML-node branch; a result that is
        # already text falls through, which is what makes the flags no-ops.
        parts = extract_text(result, text_mode)
    elif is_node(result[0]):
        return serialize_node(result[0])
    else:
        parts = [scalar_text(r) for r in result]

    lines = [line for line in (clean(part) for part in parts) if line]
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
        root, is_html = parse_document(data)
    except XMLInputError as exc:
        return fail(str(exc))

    text_mode = ALL if args.text_all else (DIRECT if args.text else None)

    query = args.QUERY
    if args.css:
        translator = HTMLTranslator() if is_html else GenericTranslator()
        try:
            query, css_mode = compile_css(query, translator)
        except QueryError as exc:
            return fail(str(exc))
        if css_mode is not None:
            text_mode = css_mode

    try:
        result = evaluate(root, query)
    except QueryError as exc:
        return fail(str(exc))

    output = render(result, text_mode)
    if output:
        sys.stdout.buffer.write(output.encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
