#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Input is always read from stdin; INFILE is accepted but ignored.
"""

import argparse
import copy
import json
import re
import sys

import cssselect
from cssselect import GenericTranslator, HTMLTranslator, SelectorError
from cssselect.parser import CombinedSelector, Element, Selector
from lxml import etree

PROG = "xjq"

# Heuristic markers that mean "this is really an HTML document", used to decide
# whether a strict-XML failure should be retried with the HTML parser.
_HTML_HINT = re.compile(
    rb"<!DOCTYPE\s+html|<html[\s>]|<HTML[\s>]|<body[\s>]|<BODY[\s>]", re.IGNORECASE
)

_WS = re.compile(r"\s+")

# The two flavours of text extraction, shared by the flags and by ``::text``.
DIRECT = "direct"
ALL = "all"

TEXT_PSEUDO = "text"


def die(message, code=1):
    sys.stderr.write("%s: %s\n" % (PROG, message))
    sys.exit(code)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Evaluate an XPath 1.0 or CSS query against XML/HTML read from stdin.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression or CSS selector")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; input is always read from stdin",
    )
    parser.add_argument(
        "--css",
        action="store_true",
        help="interpret QUERY as a CSS selector instead of an XPath expression",
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="extract the direct text of each matched element",
    )
    parser.add_argument(
        "--text-all",
        dest="text_all",
        action="store_true",
        help="extract every descendant text node of each matched element",
    )
    # Unknown options are ignored rather than fatal: the interface promises
    # OPTIONS but assigns no meaning to the rest of them.
    args, _unknown = parser.parse_known_args(argv)
    return args


def flag_text_mode(args):
    """``--text-all`` outranks ``--text`` when both are given."""
    if args.text_all:
        return ALL
    if args.text:
        return DIRECT
    return None


def read_input():
    try:
        data = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        data = sys.stdin.read().encode("utf-8", "replace")
    if not data or not data.strip():
        die("failed to parse xml input: empty input")
    return data


def parse_document(data):
    """Parse as XML; retry as HTML only for documents that really look like HTML.

    Returns ``(root, is_html)`` so CSS translation can pick matching casing rules.
    """
    xml_parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
    try:
        return etree.fromstring(data, xml_parser), False
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
    return root, True


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


# --------------------------------------------------------------------------
# JSON input
# --------------------------------------------------------------------------

JSON_ROOT = "root"
JSON_ITEM = "item"
TYPE_ATTR = "type"

# Sentinel for "stdin is not a JSON object/array", so that a genuine ``null``
# document could never be confused with the absence of one.
NOT_JSON = object()

# XML 1.0 Name, minus ``:``: a colon in a key reads as a namespace prefix, and
# a converted document has no prefix to bind it to.
_NAME_START = (
    r"A-Za-z_"
    r"\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    r"\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    r"\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_REST = _NAME_START + r"0-9\-.\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile(r"[%s][%s]*\Z" % (_NAME_START, _NAME_REST))


def detect_json(data):
    """Decode stdin as a JSON object/array, or return ``NOT_JSON``.

    Only objects and arrays count: a top-level primitive is not JSON input for
    this mode and falls through to the XML/HTML parser, as does anything that
    fails to decode.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return NOT_JSON
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped or stripped[0] not in "{[":
        return NOT_JSON
    try:
        document = json.loads(text)
    except ValueError:
        return NOT_JSON
    if isinstance(document, (dict, list)):
        return document
    return NOT_JSON


def json_type(value):
    """The ``type`` attribute for a decoded JSON value.

    ``bool`` is tested before ``int`` because it is a subclass of it.
    """
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


def format_json_number(value):
    """Minimal string form: ``1 -> 1``, ``1.0 -> 1``, ``1.50 -> 1.5``."""
    if isinstance(value, int):
        return str(value)
    value = float(value)
    if value != value:
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    text = repr(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def json_text(value, kind):
    """The element text for a primitive value; ``None`` leaves the element empty."""
    if kind == "str":
        return value
    if kind == "bool":
        return "true" if value else "false"
    if kind in ("int", "float"):
        return format_json_number(value)
    return None  # null, and the containers, hold no text of their own


def make_element(tag, kind):
    try:
        element = etree.Element(tag)
    except ValueError:
        die("invalid json key %r: not a valid xml element name" % (tag,))
    element.set(TYPE_ATTR, kind)
    return element


def build_element(tag, value, kind):
    element = make_element(tag, kind)
    if kind == "dict":
        for key, child_value in value.items():
            if not isinstance(key, str) or not _XML_NAME.match(key):
                die("invalid json key %r: not a valid xml element name" % (key,))
            element.append(build_element(key, child_value, json_type(child_value)))
    elif kind == "list":
        for entry in value:
            element.append(build_element(JSON_ITEM, entry, json_type(entry)))
    else:
        element.text = json_text(value, kind)
    return element


def json_to_xml(document):
    """Convert a decoded JSON document to a ``<root>`` element tree.

    ``<root>`` is the only element without a ``type``; a top-level array's
    entries become ``<item>`` children of it, exactly as nested arrays do.
    """
    root = build_element(JSON_ROOT, document, json_type(document))
    del root.attrib[TYPE_ATTR]
    return root


# --------------------------------------------------------------------------
# CSS support
# --------------------------------------------------------------------------


def _is_universal(tree):
    """True for a bare ``*`` with no namespace and no further filters."""
    return isinstance(tree, Element) and tree.element is None and tree.namespace is None


def _split_text_selector(selector):
    """Return ``(host_tree, mode)`` for one comma-separated CSS selector.

    ``mode`` is ``None`` when the selector carries no ``::text`` pseudo-element,
    ``ALL`` for the ``sel ::text`` (descendant) spelling and ``DIRECT`` for the
    ``sel::text`` spelling.
    """
    pseudo = selector.pseudo_element
    tree = selector.parsed_tree
    if pseudo is None:
        return tree, None
    if not isinstance(pseudo, str):
        # e.g. ``::text()`` -- a functional pseudo-element, which we never define.
        raise SelectorError("unsupported functional pseudo-element")
    if pseudo != TEXT_PSEUDO:
        raise SelectorError("unsupported pseudo-element '::%s'" % pseudo)
    # ``sel ::text`` parses as ``sel *`` plus the pseudo-element: the implicit
    # universal selector behind a descendant combinator is what distinguishes it
    # from ``sel::text``.
    if (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and _is_universal(tree.subselector)
    ):
        return tree.selector, ALL
    return tree, DIRECT


def compile_css(query, is_html):
    """Translate a CSS query into ``(xpath, text_mode)``.

    ``text_mode`` is ``None`` unless the query used ``::text``.
    """
    translator = HTMLTranslator() if is_html else GenericTranslator()
    try:
        selectors = cssselect.parse(query)
    except SelectorError as error:
        die("invalid css selector %r: %s" % (query, error))
    except Exception as error:  # cssselect can raise bare parse errors
        die("invalid css selector %r: %s" % (query, error))

    if not selectors:
        die("invalid css selector %r: empty selector" % query)

    paths = []
    modes = set()
    for selector in selectors:
        try:
            host, mode = _split_text_selector(selector)
            path = translator.selector_to_xpath(
                Selector(host, None), prefix="descendant-or-self::"
            )
        except SelectorError as error:
            die("invalid css selector %r: %s" % (query, error))
        modes.add(mode)
        paths.append(path)

    if len(modes) > 1:
        if None in modes:
            die(
                "invalid css selector %r: cannot mix '::text' and element "
                "selectors in one comma-separated query" % query
            )
        die(
            "invalid css selector %r: cannot mix 'sel::text' and 'sel ::text' "
            "in one comma-separated query" % query
        )

    return " | ".join(paths), modes.pop()


def select_css(root, xpath, namespaces):
    try:
        return root.xpath(xpath, namespaces=namespaces) if namespaces else root.xpath(xpath)
    except etree.XPathError as error:
        die("invalid css selector: %s" % error)


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------


def normalize(text):
    return _WS.sub(" ", text).strip()


def _is_markup_only(node):
    return isinstance(node, (etree._Comment, etree._ProcessingInstruction, etree._Entity))


def direct_text(element):
    """The element's own child text nodes, concatenated."""
    parts = [element.text or ""]
    for child in element:
        parts.append(child.tail or "")
    return "".join(parts)


def descendant_texts(element):
    """Every descendant-or-self text node, in document order."""
    chunks = []
    if element.text:
        chunks.append(element.text)
    for child in element:
        if not _is_markup_only(child):
            chunks.extend(descendant_texts(child))
        if child.tail:
            chunks.append(child.tail)
    return chunks


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


def extract_text(result, mode):
    """Render a query result as text lines under ``mode``.

    Items that are already strings (``text()``, ``::text``, attributes) pass
    straight through, which is what makes the flags no-ops for such queries.
    """
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, (float, int)):
        return format_number(float(result))
    if not isinstance(result, list):
        result = [result]

    lines = []
    for item in result:
        if isinstance(item, etree._ElementTree):
            item = item.getroot()
        if isinstance(item, etree._Element) and not _is_markup_only(item):
            chunks = descendant_texts(item) if mode == ALL else [direct_text(item)]
            for chunk in chunks:
                text = normalize(chunk)
                if text:
                    lines.append(text)
            continue
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


def render(result):
    """Turn a query result into the text to print (or None for no output)."""
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
    mode = flag_text_mode(args)

    data = read_input()
    document = detect_json(data)
    if document is NOT_JSON:
        root, is_html = parse_document(data)
    else:
        root, is_html = json_to_xml(document), False
    namespaces = namespaces_for(root)

    if args.css:
        xpath, css_mode = compile_css(args.query, is_html)
        result = select_css(root, xpath, namespaces)
        # An explicit ``::text`` fixes the mode; the flags only fill in the gap.
        mode = css_mode or mode
    else:
        result = evaluate(root, args.query, namespaces)

    output = extract_text(result, mode) if mode else render(result)
    if output:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
