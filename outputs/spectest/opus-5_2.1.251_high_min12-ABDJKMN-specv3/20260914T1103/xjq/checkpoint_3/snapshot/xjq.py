#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import copy
import json
import math
import re
import sys

from cssselect import GenericTranslator, HTMLTranslator, SelectorError
from lxml import etree

WHITESPACE_RUN = re.compile(r"\s+")
HTML_MARKER = re.compile(rb"<!DOCTYPE\s+html|<html[\s>]", re.IGNORECASE)
INDENT = "  "

# JSON auto-detection: only a top-level object or array counts as JSON input,
# so the first non-whitespace byte has to open one of them.  Anything else --
# including a top-level primitive -- is handed to the XML/HTML parser.
JSON_START = re.compile(rb"\s*[{\[]")

# XML 1.0 NCName, i.e. a Name without the ":" that would make it a namespace
# prefix (lxml refuses those as tag names anyway).
_NAME_START = (
    "A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d"
    "\u037f-\u1fff\u200c-\u200d\u2070-\u218f\u2c00-\u2fef"
    "\u3001-\ud7ff\uf900-\ufdcf\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_CHAR = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
XML_NAME = re.compile("[%s][%s]*\\Z" % (_NAME_START, _NAME_CHAR))

ROOT_TAG = "root"
ITEM_TAG = "item"

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


class JSONInputError(Exception):
    """stdin parsed as JSON but could not be converted to XML."""


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


def detect_json(data):
    """Return the decoded JSON object/array in `data`, or None.

    Returning None means "this is not JSON input for this mode", which sends
    the raw bytes to the XML/HTML parser instead: that covers malformed JSON,
    non-UTF-8 bytes, and top-level JSON primitives alike.
    """
    if not JSON_START.match(data):
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except ValueError:
        return None
    if not isinstance(value, (dict, list)):
        return None
    return value


def _reject_constant(name):
    # `NaN`/`Infinity` are Python extensions, not JSON; refusing them keeps
    # detection to what RFC 8259 calls JSON.
    raise ValueError("unexpected constant %r" % name)


def json_type(value):
    """The `type` attribute for a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    return "list"


def json_number(value):
    """Minimal string form of a JSON number: `1.0 -> "1"`, `1.50 -> "1.5"`."""
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):
        return repr(value)
    if value == int(value):
        return str(int(value))
    return repr(value)


def json_text(value):
    """Element text for a primitive JSON value; null is the empty string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json_number(value)
    return value


def check_key(key):
    """Return `key` if it can be an XML element name, else raise."""
    if not isinstance(key, str) or not XML_NAME.match(key):
        raise JSONInputError(
            "invalid json key %r: not a valid xml element name" % (key,)
        )
    return key


def build_json_element(parent, tag, value):
    """Append the element for one JSON value (dicts and lists recurse)."""
    element = etree.SubElement(parent, tag)
    element.set("type", json_type(value))
    if isinstance(value, dict):
        for key, child in value.items():
            build_json_element(element, check_key(key), child)
    elif isinstance(value, list):
        for child in value:
            build_json_element(element, ITEM_TAG, child)
    else:
        # Always a string, never None, so null serializes as `<a></a>` rather
        # than a self-closing tag.
        element.text = json_text(value)
    return element


def json_to_xml(value):
    """Convert a decoded JSON object/array into a `<root>` element tree.

    `<root>` is the only element without a `type`; object keys keep both their
    order and their case, and array entries become `<item>`.
    """
    root = etree.Element(ROOT_TAG)
    try:
        if isinstance(value, dict):
            for key, child in value.items():
                build_json_element(root, check_key(key), child)
        else:
            for child in value:
                build_json_element(root, ITEM_TAG, child)
    except ValueError as exc:
        raise JSONInputError("invalid json input: %s" % _first_line(exc))
    return root


def parse_document(data):
    """Parse `data` (bytes) as JSON, XML, or HTML, whichever it looks like.

    Element names keep their case in both paths for the names a query can
    reach: the XML parser never folds case, and the HTML fallback only runs
    for documents that announce themselves as HTML.

    Returns `(root, is_html)`; `is_html` picks the CSS translator later.
    """
    if not data.strip():
        raise XMLInputError("empty xml input: nothing to parse")

    decoded = detect_json(data)
    if decoded is not None:
        return json_to_xml(decoded), False

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
    except (XMLInputError, JSONInputError) as exc:
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
