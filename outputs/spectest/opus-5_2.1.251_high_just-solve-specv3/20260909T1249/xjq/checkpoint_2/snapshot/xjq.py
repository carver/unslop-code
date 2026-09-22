#!/usr/bin/env python3
"""xjq - query XML from stdin with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import re
import sys

from lxml import etree

import cssselect
from cssselect import GenericTranslator, HTMLTranslator, SelectorError
from cssselect.parser import CombinedSelector, Element, FunctionalPseudoElement
from cssselect.xpath import ExpressionError
from cssselect.xpath import XPathExpr as _XPathExpr

_WS = re.compile(r"\s+")
_LOOKS_LIKE_HTML = re.compile(rb"<!doctype\s+html|<html[\s>]", re.IGNORECASE)
_XPATH_TEXT_FN = re.compile(r"\btext\s*\(\s*\)")

TEXT_PSEUDO = "text"
DIRECT = "direct"
DESCENDANT = "all"


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
    """Parse XML case-sensitively; fall back to HTML only for HTML documents.

    Returns (root, parsed_as_html).
    """
    if not data.strip():
        die("xjq: error: could not parse xml input: input is empty")

    try:
        parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
        return etree.fromstring(data, parser), False
    except etree.XMLSyntaxError as exc:
        xml_error = exc

    if _LOOKS_LIKE_HTML.search(data):
        try:
            html_parser = etree.HTMLParser(recover=True)
            root = etree.fromstring(data, html_parser)
            if root is not None and len(root) or (root is not None and root.text):
                return root, True
        except etree.XMLSyntaxError:
            pass

    die("xjq: error: failed to parse xml input: %s" % xml_error)


# --------------------------------------------------------------------------
# CSS support
# --------------------------------------------------------------------------


class TextXPathExpr(_XPathExpr):
    """XPathExpr that knows how to turn its subject into a text() step."""

    textnode = False

    def __str__(self):
        path = super().__str__()
        if self.textnode:
            if path == "*":
                path = "text()"
            elif path.endswith("::*/*"):
                path = path[:-3] + "text()"
            else:
                path += "/text()"
        return path

    def join(self, combiner, other, *args, **kwargs):
        super().join(combiner, other, *args, **kwargs)
        self.textnode = getattr(other, "textnode", False)
        return self


class _TextPseudoMixin:
    """Adds support for the custom ``::text`` pseudo-element."""

    xpathexpr_cls = TextXPathExpr

    def xpath_pseudo_element(self, xpath, pseudo_element):
        if isinstance(pseudo_element, FunctionalPseudoElement):
            raise ExpressionError(
                "The pseudo-element ::%s() is not supported" % pseudo_element.name
            )
        if pseudo_element != TEXT_PSEUDO:
            raise ExpressionError(
                "The pseudo-element ::%s is not supported" % pseudo_element
            )
        xpath.textnode = True
        return xpath


class TextGenericTranslator(_TextPseudoMixin, GenericTranslator):
    pass


class TextHTMLTranslator(_TextPseudoMixin, HTMLTranslator):
    pass


def _is_universal(node):
    return (
        isinstance(node, Element)
        and node.element is None
        and node.namespace is None
    )


def _text_mode(selector):
    """Return DIRECT or DESCENDANT for a ``::text`` selector."""
    tree = getattr(selector, "parsed_tree", None)
    if (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and _is_universal(tree.subselector)
    ):
        return DESCENDANT
    return DIRECT


def translate_css(query, is_html=False):
    """Translate a CSS group of selectors into XPath.

    Returns (xpath_expression, text_mode) where text_mode is None (node
    output), DIRECT (elements whose direct text is wanted) or DESCENDANT
    (the expression already selects text nodes).
    """
    translator = TextHTMLTranslator() if is_html else TextGenericTranslator()

    try:
        selectors = cssselect.parse(query)
    except SelectorError as exc:
        die("xjq: error: invalid css selector %r: %s" % (query, exc))

    if not selectors:
        die("xjq: error: invalid css selector %r: empty selector" % query)

    modes = set()
    for selector in selectors:
        pseudo = selector.pseudo_element
        if pseudo is None:
            modes.add(None)
        elif isinstance(pseudo, FunctionalPseudoElement):
            die(
                "xjq: error: invalid css selector %r: the pseudo-element ::%s() is "
                "not supported" % (query, pseudo.name)
            )
        elif str(pseudo) == TEXT_PSEUDO:
            modes.add(_text_mode(selector))
        else:
            die(
                "xjq: error: invalid css selector %r: the pseudo-element ::%s is "
                "not supported" % (query, pseudo)
            )

    if DIRECT in modes and DESCENDANT in modes:
        die(
            "xjq: error: invalid css selector %r: cannot mix direct (sel::text) and "
            "descendant (sel ::text) text extraction in one query" % query
        )
    if None in modes and len(modes) > 1:
        die(
            "xjq: error: invalid css selector %r: cannot mix ::text and element "
            "selectors in one query" % query
        )

    # ``sel::text`` selects the elements themselves; their direct text is joined
    # into one line per element (exactly like --text).  ``sel ::text`` selects
    # the descendant text nodes directly, one node per line.
    mode = DESCENDANT if DESCENDANT in modes else (DIRECT if DIRECT in modes else None)

    try:
        expression = " | ".join(
            translator.selector_to_xpath(
                selector, translate_pseudo_elements=(mode == DESCENDANT)
            )
            for selector in selectors
        )
    except SelectorError as exc:
        die("xjq: error: invalid css selector %r: %s" % (query, exc))

    return expression, mode


# --------------------------------------------------------------------------
# Query execution
# --------------------------------------------------------------------------


def compile_and_run(root, query, display=None, kind="xpath expression"):
    display = query if display is None else display
    nsmap = {p: u for p, u in (root.nsmap or {}).items() if p}
    try:
        xpath = etree.XPath(query, namespaces=nsmap or None, smart_strings=True)
    except (etree.XPathSyntaxError, etree.XPathError, ValueError) as exc:
        die("xjq: error: invalid %s %r: %s" % (kind, display, exc))

    try:
        return xpath(root.getroottree())
    except (etree.XPathEvalError, etree.XPathError) as exc:
        die("xjq: error: invalid %s %r: %s" % (kind, display, exc))


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


def element_text(node, mode):
    """Direct or descendant text of a single node."""
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
    if isinstance(node, etree._Element):
        if not isinstance(node.tag, str):  # comment / processing instruction
            return node.text or ""
        axis = "descendant-or-self::text()" if mode == DESCENDANT else "text()"
        return "".join(node.xpath(axis))
    return format_scalar(node)


def extract_text(result, mode):
    """One text value per matched element, in document order."""
    return [element_text(item, mode) for item in result]


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
        description="Query XML read from stdin using XPath 1.0 or a CSS selector.",
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
        action="store_true",
        help="extract all descendant text of each matched element",
    )
    parser.add_argument(
        "-v", "--version", action="version", version="xjq 1.0",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    # --text-all wins when both are given.
    text_mode = DESCENDANT if args.text_all else (DIRECT if args.text else None)

    data = read_stdin()
    root, is_html = parse_document(data)

    if args.css:
        expression, css_mode = translate_css(args.query, is_html)
        result = compile_and_run(root, expression, args.query, "css selector")
        # A ::text query already extracts text: --text/--text-all are no-ops.
        if css_mode == DIRECT:
            text_mode = DIRECT
        elif css_mode == DESCENDANT:
            text_mode = None  # the expression selected the text nodes itself
    else:
        # An XPath that already extracts text makes the flags no-ops too.
        if _XPATH_TEXT_FN.search(args.query):
            text_mode = None
        result = compile_and_run(root, args.query)

    if text_mode and isinstance(result, list):
        result = extract_text(result, text_mode)
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
