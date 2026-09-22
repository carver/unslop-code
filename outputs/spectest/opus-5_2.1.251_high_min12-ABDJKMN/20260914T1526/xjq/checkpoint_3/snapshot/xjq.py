#!/usr/bin/env python3
"""xjq.py -- query XML/HTML/JSON read from stdin with XPath 1.0 or a CSS selector.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

QUERY is an XPath 1.0 expression, or a CSS selector when `--css` is given;
INFILE is accepted but ignored -- the document is always read from stdin.
A top-level JSON object or array on stdin is auto-detected and converted to
XML before the query runs; anything else is parsed as XML/HTML.
"""
import argparse
import copy
import json
import math
import re
import sys

import cssselect
from cssselect.parser import CombinedSelector, Element, Selector
from cssselect.xpath import GenericTranslator
from lxml import etree

WHITESPACE = re.compile(r"\s+")

# The custom `::text` pseudo-element and its two modes: `sel::text` takes the
# element's own text, `sel ::text` takes every text node beneath it.
TEXT_PSEUDO = "text"
DIRECT = "direct"
DESCENDANT = "descendant"

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
        description="Query XML/HTML from stdin with an XPath 1.0 expression "
                    "or a CSS selector.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression, or CSS selector with --css")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility but ignored; input is read from stdin",
    )
    parser.add_argument(
        "--css",
        action="store_true",
        help="interpret QUERY as a CSS selector",
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="direct text extraction from matched elements",
    )
    parser.add_argument(
        "--text-all",
        dest="text_all",
        action="store_true",
        help="descendant text extraction from matched elements",
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


# ---------------------------------------------------------------------------
# JSON input
# ---------------------------------------------------------------------------
ITEM_TAG = "item"


def detect_json(data):
    """Return the parsed JSON container, or None when the input is not JSON.

    Only top-level objects and arrays count as JSON input; primitives and
    anything that does not parse fall back to XML/HTML (AMBIGUITIES T26).
    """
    try:
        value = json.loads(data)
    except ValueError:
        return None
    except (TypeError, UnicodeDecodeError):
        return None
    if isinstance(value, (dict, list)):
        return value
    return None


def json_type(value):
    """The `type` attribute for a converted value (Python's own type names)."""
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
    """Minimal string form of a JSON number (AMBIGUITIES T25)."""
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def json_text(value):
    """Element text for a JSON primitive; None when the element stays empty."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json_number(value)
    return value or None


def make_child(parent, tag):
    """Append a child element, rejecting keys that are not XML names."""
    try:
        return etree.SubElement(parent, tag)
    except (ValueError, TypeError):
        die("invalid json key %r: not a valid XML element name" % (tag,))


def fill_element(element, value):
    """Populate one element from a JSON value, recursing into containers."""
    if isinstance(value, dict):
        for key, sub in value.items():
            child = make_child(element, key)
            child.set("type", json_type(sub))
            fill_element(child, sub)
    elif isinstance(value, list):
        for entry in value:
            child = etree.SubElement(element, ITEM_TAG)
            child.set("type", json_type(entry))
            fill_element(child, entry)
    else:
        element.text = json_text(value)


def json_to_xml(value):
    """Convert a top-level JSON object/array into a `<root>` element tree."""
    root = etree.Element("root")  # `<root>` never carries `type`.
    fill_element(root, value)
    return root


def build_document(data):
    """Turn stdin bytes into an element tree, auto-detecting JSON input."""
    value = detect_json(data)
    if value is not None:
        return json_to_xml(value)
    return parse_document(data)


def evaluate(root, query):
    """Evaluate the XPath, or exit 1 with a message mentioning xpath."""
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        die("invalid xpath expression %r: %s" % (query, first_line(exc)))
    except (TypeError, ValueError) as exc:  # e.g. non-string query internals
        die("invalid xpath expression %r: %s" % (query, first_line(exc)))


# ---------------------------------------------------------------------------
# CSS query mode
# ---------------------------------------------------------------------------
def is_universal(tree):
    """True for the implicit `*` that `sel ::text` attaches its pseudo to."""
    return (
        isinstance(tree, Element)
        and tree.element is None
        and tree.namespace is None
    )


def selector_text_mode(selector, query):
    """Split one parsed selector into (text mode, element-matching tree)."""
    pseudo = selector.pseudo_element
    tree = selector.parsed_tree
    if pseudo is None:
        return None, tree
    if str(pseudo).lower() != TEXT_PSEUDO:
        die("invalid css selector %r: unsupported pseudo-element ::%s" % (query, pseudo))
    # `sel ::text` parses as `sel` <descendant> `*` carrying the pseudo; the
    # elements to read text from are the left-hand side (AMBIGUITIES T21).
    if (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and is_universal(tree.subselector)
    ):
        return DESCENDANT, tree.selector
    return DIRECT, tree


def compile_css(query):
    """Translate a CSS query into (xpath, text mode), or exit 1."""
    try:
        selectors = cssselect.parse(query)
    except cssselect.SelectorError as exc:
        die("invalid css selector %r: %s" % (query, first_line(exc)))
    except Exception as exc:  # cssselect can raise on pathological input
        die("invalid css selector %r: %s" % (query, first_line(exc)))

    translator = GenericTranslator()
    modes = []
    paths = []
    for selector in selectors:
        mode, tree = selector_text_mode(selector, query)
        modes.append(mode)
        try:
            paths.append(translator.selector_to_xpath(Selector(tree, None)))
        except cssselect.SelectorError as exc:
            die("invalid css selector %r: %s" % (query, first_line(exc)))

    if len(set(modes)) > 1:
        die(
            "invalid css query %r: cannot mix ::text modes in one "
            "comma-separated selector" % query
        )
    return " | ".join(paths), modes[0]


def evaluate_css(root, query):
    """Match a CSS query, returning (results, text mode)."""
    path, mode = compile_css(query)
    try:
        return root.xpath(path), mode
    except etree.XPathError as exc:
        die("invalid css selector %r: %s" % (query, first_line(exc)))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
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


def is_element(value):
    """True for element nodes only (not comments or processing instructions)."""
    return is_node(value) and isinstance(value.tag, str)


def element_text(element, mode):
    """Text lines for one element: its own text, or every descendant text node."""
    if mode == DESCENDANT:
        parts = list(element.xpath("descendant::text()"))
    else:
        parts = ["".join(element.xpath("text()"))]
    return [text for text in (collapse(part) for part in parts) if text]


def extract_text(results, mode):
    """Text lines for a result list, leaving non-element results alone."""
    lines = []
    for item in results:
        if is_element(item):
            lines.extend(element_text(item, mode))
        else:
            text = collapse(format_scalar(item))
            if text:
                lines.append(text)
    return lines


def serialize_node(node):
    """Pretty-print a single node, without its tail text."""
    node = copy.deepcopy(node)
    node.tail = None
    text = etree.tostring(node, pretty_print=True)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return text.rstrip("\n")


def render(result, mode=None):
    """Turn a query result into the text to write to stdout, or None."""
    # Text extraction only applies where there are elements to read text from;
    # a query that already yields text is left alone (AMBIGUITIES T17, T22).
    if mode is not None and isinstance(result, list) and any(is_element(i) for i in result):
        lines = extract_text(result, mode)
        return "\n".join(lines) if lines else None

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


def flag_text_mode(args):
    """--text-all wins when both text flags are present."""
    if args.text_all:
        return DESCENDANT
    if args.text:
        return DIRECT
    return None


def main(argv=None):
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    root = build_document(read_stdin())

    if args.css:
        results, mode = evaluate_css(root, args.query)
    else:
        results, mode = evaluate(root, args.query), None

    if mode is None:
        mode = flag_text_mode(args)

    output = render(results, mode)
    if output is not None:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
