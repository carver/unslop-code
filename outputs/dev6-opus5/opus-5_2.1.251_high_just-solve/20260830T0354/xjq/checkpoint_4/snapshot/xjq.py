#!/usr/bin/env python3
"""xjq -- query XML, HTML or JSON from stdin with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Reads an XML (or HTML, or JSON) document from ``INFILE`` -- or from stdin when
no file is given -- evaluates QUERY against it and prints the results.  A JSON
object or array is auto-detected and converted to XML (wrapped in ``<root>``)
before the query runs; anything else is parsed as XML/HTML.  Text and attribute
results are whitespace-normalised and printed one per line; node results are
pretty-printed as XML unless ``--compact`` is given.  ``--first`` keeps only the
first result of whatever kind the query produced.

QUERY is an XPath 1.0 expression unless ``--css`` is given, in which case it is
a CSS selector which additionally understands the custom ``::text``
pseudo-element (``sel::text`` for direct text, ``sel ::text`` for every
descendant text node).  ``--text``/``--text-all`` apply the same two kinds of
text extraction to whatever the query matched.
"""

import argparse
import copy
import io
import json
import math
import re
import sys

from lxml import etree

from cssselect import GenericTranslator, HTMLTranslator, SelectorError
from cssselect.parser import FunctionalPseudoElement
from cssselect.parser import parse as css_parse
from cssselect.xpath import ExpressionError, XPathExpr

WHITESPACE = re.compile(r"\s+")

HTML_HINT = re.compile(rb"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]", re.I)

DIRECT = "direct"
ALL = "all"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML, HTML or JSON from stdin using XPath 1.0 or a CSS selector.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression or CSS selector")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="file to read the document from (takes precedence over stdin)",
    )
    parser.add_argument(
        "extra",
        metavar="...",
        nargs="*",
        default=[],
        help=argparse.SUPPRESS,
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
        help="extract the direct text of every matched element",
    )
    parser.add_argument(
        "--text-all",
        dest="text_all",
        action="store_true",
        help="extract every descendant text node of the matched elements",
    )
    parser.add_argument(
        "-f",
        "--first",
        action="store_true",
        help="return only the first result",
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialise XML results without added pretty-print formatting",
    )
    return parser


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


def read_stdin():
    try:
        data = sys.stdin.buffer.read()
    except AttributeError:  # pragma: no cover - stdin replaced by a text stream
        data = sys.stdin.read().encode("utf-8", "replace")
    except Exception as exc:
        die("xjq: error: could not read xml input from stdin: %s" % exc)
    return data


def read_infile(path):
    """Read ``path`` as UTF-8 text (an optional BOM is stripped).

    The bytes handed back are always UTF-8 without a BOM so that the XML parser
    and the JSON auto-detection both see the same thing.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        die(
            "xjq: error: could not read input file %r: %s"
            % (path, exc.strerror or exc)
        )
    except Exception as exc:  # pragma: no cover - defensive
        die("xjq: error: could not read input file %r: %s" % (path, exc))

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        die(
            "xjq: error: could not read input file %r: the file is not valid "
            "utf-8 text: %s" % (path, exc)
        )
    return text.encode("utf-8")


# --------------------------------------------------------------------------
# JSON input
# --------------------------------------------------------------------------

# XML 1.0 (fifth edition) NCName: a Name without a namespace colon.  JSON keys
# that do not match are not usable as element tag names.
NAME_START = (
    "A-Z_a-z"
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
# A literal "-" must stay last so it is not read as a character range.
NAME_CHAR = NAME_START + ".0-9\u00b7\u0300-\u036f\u203f\u2040-"
XML_NAME = re.compile("^[%s][%s]*$" % (NAME_START, NAME_CHAR))


def detect_json(data):
    """Return the JSON document held in ``data``, or ``None``.

    Only top-level objects and arrays count as JSON input; top-level primitives
    (and anything that does not parse) fall back to the XML/HTML parser.
    """
    try:
        text = data.decode("utf-8-sig")
    except (UnicodeDecodeError, AttributeError):
        return None
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return document if isinstance(document, (dict, list)) else None


def json_type(value):
    """The ``type`` attribute for a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # bool before int: bool is an int subclass
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


def json_number_text(value):
    """The minimal string form of a JSON number: 1.0 -> "1", 1.50 -> "1.5"."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


def json_text(value):
    """The element text for a primitive JSON value (empty for null)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json_number_text(value)
    return value


def json_tag(key):
    """Validate a JSON object key for use as an element name."""
    if not isinstance(key, str) or not XML_NAME.match(key):
        die(
            "xjq: error: invalid json input: the key %r is not a valid xml "
            "element name" % (key,)
        )
    return key


def build_json_element(element, value):
    """Fill ``element`` with the conversion of ``value``."""
    if isinstance(value, dict):
        for key, child_value in value.items():
            child = add_json_child(element, json_tag(key), child_value)
            build_json_element(child, child_value)
    elif isinstance(value, list):
        for child_value in value:
            child = add_json_child(element, "item", child_value)
            build_json_element(child, child_value)
    else:
        text = json_text(value)
        if text:
            element.text = text


def add_json_child(parent, tag, value):
    try:
        child = etree.SubElement(parent, tag)
    except ValueError:  # pragma: no cover - XML_NAME already rejects these
        die(
            "xjq: error: invalid json input: the key %r is not a valid xml "
            "element name" % (tag,)
        )
    child.set("type", json_type(value))
    return child


def json_to_tree(document):
    """Convert a JSON object/array into a ``<root>``-wrapped XML tree."""
    root = etree.Element("root")
    build_json_element(root, document)
    return etree.ElementTree(root)


def parse_document(data):
    """Parse the input, raising a friendly error for malformed/empty input.

    A JSON object or array is auto-detected and converted to XML; everything
    else is parsed as XML, falling back to HTML.

    Returns ``(tree, is_html)``.
    """
    if not data or not data.strip():
        die("xjq: error: failed to parse xml input: the document is empty")

    document = detect_json(data)
    if document is not None:
        try:
            return json_to_tree(document), False
        except RecursionError:
            die("xjq: error: invalid json input: the document is nested too deeply")

    xml_parser = etree.XMLParser(
        remove_blank_text=True,
        resolve_entities=False,
        no_network=True,
        recover=False,
    )
    try:
        return etree.parse(io.BytesIO(data), xml_parser), False
    except etree.XMLSyntaxError as xml_error:
        if HTML_HINT.search(data[:4096]):
            tree = parse_html(data)
            if tree is not None:
                return tree, True
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


# --------------------------------------------------------------------------
# CSS support (with the custom ::text pseudo-element)
# --------------------------------------------------------------------------


class TextXPathExpr(XPathExpr):
    """An XPath expression that may be redirected onto text nodes."""

    def __init__(self, path="", element="*", condition="", star_prefix=False):
        super().__init__(path, element, condition, star_prefix)
        self.textnode = False

    @classmethod
    def from_xpath(cls, xpath, textnode=False):
        expr = cls(xpath.path, xpath.element, xpath.condition)
        expr.textnode = textnode
        return expr

    def __str__(self):
        path = super().__str__()
        if self.textnode:
            if path == "*":
                # A bare "::text": every text node in the subtree.
                path = "text()"
            elif path.endswith("::*/*"):
                # "sel ::text": the descendant combinator makes it every text
                # node below the matched elements.
                path = path[:-3] + "text()"
            else:
                # "sel::text": only the direct text children.
                path += "/text()"
        return path

    def join(self, combiner, other, *args, **kwargs):
        super().join(combiner, other, *args, **kwargs)
        self.textnode = getattr(other, "textnode", False)
        return self


class TextTranslatorMixin:
    """Teach a cssselect translator about ``::text``."""

    xpathexpr_cls = TextXPathExpr

    def xpath_pseudo_element(self, xpath, pseudo_element):
        if isinstance(pseudo_element, FunctionalPseudoElement):
            raise ExpressionError(
                "the pseudo-element ::%s() is not supported" % pseudo_element.name
            )
        if str(pseudo_element) != "text":
            raise ExpressionError(
                "the pseudo-element ::%s is not supported" % pseudo_element
            )
        return TextXPathExpr.from_xpath(xpath, textnode=True)


class TextGenericTranslator(TextTranslatorMixin, GenericTranslator):
    pass


class TextHTMLTranslator(TextTranslatorMixin, HTMLTranslator):
    pass


def text_pseudo_mode(translator, selector):
    """Return DIRECT or ALL for a selector carrying the ``::text`` pseudo."""
    path = str(translator.xpath(selector.parsed_tree))
    if path == "*" or path.endswith("::*/*"):
        return ALL
    return DIRECT


def compile_css(query, is_html):
    """Translate a CSS selector to XPath.

    Returns ``(xpath, text_mode)`` where ``text_mode`` is ``None`` when the
    selector does not use ``::text``.
    """
    translator = TextHTMLTranslator() if is_html else TextGenericTranslator()

    try:
        selectors = css_parse(query)
    except SelectorError as exc:
        die("xjq: error: invalid css selector %r: %s" % (query, exc))
    except Exception as exc:  # pragma: no cover - defensive
        die("xjq: error: invalid css selector %r: %s" % (query, exc))

    if not selectors:
        die("xjq: error: invalid css selector %r: the selector is empty" % query)

    modes = []
    for selector in selectors:
        pseudo = selector.pseudo_element
        if pseudo is None:
            modes.append(None)
            continue
        if not isinstance(pseudo, FunctionalPseudoElement) and str(pseudo) == "text":
            try:
                modes.append(text_pseudo_mode(translator, selector))
            except SelectorError as exc:
                die("xjq: error: invalid css selector %r: %s" % (query, exc))
            continue
        name = pseudo.name + "()" if isinstance(pseudo, FunctionalPseudoElement) else str(pseudo)
        die(
            "xjq: error: invalid css selector %r: the pseudo-element ::%s is not "
            "supported" % (query, name)
        )

    distinct = set(modes)
    if len(distinct) > 1:
        if DIRECT in distinct and ALL in distinct:
            die(
                "xjq: error: invalid css selector %r: cannot mix direct "
                "('sel::text') and descendant ('sel ::text') text extraction in a "
                "comma-separated selector" % query
            )
        die(
            "xjq: error: invalid css selector %r: cannot mix ::text and element "
            "selectors in a comma-separated selector" % query
        )

    try:
        xpath = " | ".join(
            translator.selector_to_xpath(selector, translate_pseudo_elements=True)
            for selector in selectors
        )
    except SelectorError as exc:
        die("xjq: error: invalid css selector %r: %s" % (query, exc))

    return xpath, modes[0]


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def evaluate(tree, query, expression=None, kind="xpath expression"):
    """Evaluate an XPath expression against the parsed document."""
    expression = query if expression is None else expression
    if expression.strip() == "/":
        # lxml returns an empty node-set for the bare document node.
        return [tree]
    try:
        return tree.xpath(expression, namespaces=namespaces(tree), smart_strings=True)
    except etree.XPathError as exc:
        die("xjq: error: invalid %s %r: %s" % (kind, query, exc))
    except (TypeError, ValueError) as exc:
        die("xjq: error: invalid %s %r: %s" % (kind, query, exc))


def is_node(item):
    return isinstance(item, (etree._Element, etree._ElementTree)) and not isinstance(
        item, str
    )


def extract_text(result, mode):
    """Replace matched nodes by their text nodes."""
    if not isinstance(result, list):
        return result
    step = "text()" if mode == DIRECT else "descendant::text()"
    extracted = []
    for item in result:
        if is_node(item):
            try:
                extracted.extend(item.xpath(step, smart_strings=True))
            except etree.XPathError:  # pragma: no cover - defensive
                continue
        else:
            extracted.append(item)
    return extracted


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


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


def serialize_node(node, compact=False):
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
    node = copy.deepcopy(node)
    node.tail = None
    pretty = not compact
    try:
        text = etree.tostring(node, pretty_print=pretty, encoding="unicode")
    except (TypeError, ValueError):
        text = etree.tostring(node, pretty_print=pretty).decode("utf-8", "replace")
    return text.rstrip("\n")


def write(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:  # pragma: no cover
        pass


def first_result(result):
    """Reduce an XPath result to its first result, whatever its kind.

    Nodes, attributes and text all count; whitespace-only text nodes do not,
    since they carry nothing once normalised and are dropped from the output
    anyway.
    """
    if not isinstance(result, list):
        return result
    for item in result:
        if is_node(item) or getattr(item, "is_attribute", False):
            return [item]
        if not normalize(scalar_to_text(item)):
            continue
        return [item]
    return []


def render(result, text_only=False, compact=False):
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

    if not text_only:
        nodes = [item for item in result if is_node(item)]
        if nodes:
            return serialize_node(nodes[0], compact=compact) + "\n"

    lines = [normalize(scalar_to_text(item)) for item in result if not is_node(item)]
    if text_only:
        # Whitespace-only text nodes carry nothing once normalised.
        lines = [line for line in lines if line]
    if not any(lines):
        return ""
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Tolerate (and ignore) any unrecognised option flags.
    args, _unknown = build_parser().parse_known_args(argv)

    # --text-all wins over --text when both are given.
    if args.text_all:
        text_mode = ALL
    elif args.text:
        text_mode = DIRECT
    else:
        text_mode = None

    # A file argument wins over stdin when both are available.
    if args.infile is not None:
        data = read_infile(args.infile)
    else:
        data = read_stdin()
    tree, is_html = parse_document(data)

    query = args.query
    if args.css:
        expression, css_mode = compile_css(query, is_html)
        if css_mode is not None:
            # The query already extracts text: --text/--text-all are no-ops.
            text_mode = css_mode
            query_extracts_text = True
        else:
            query_extracts_text = False
        result = evaluate(tree, query, expression, kind="css selector")
    else:
        # An XPath such as "//p/text()" already yields text nodes; extract_text
        # passes those through untouched, so --text/--text-all are no-ops.
        query_extracts_text = False
        result = evaluate(tree, query)

    if text_mode is not None and not query_extracts_text:
        result = extract_text(result, text_mode)

    text_only = text_mode is not None
    if args.first:
        result = first_result(result)

    write(render(result, text_only=text_only, compact=args.compact))
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
