#!/usr/bin/env python3
"""xjq - query XML with XPath 1.0 or CSS selectors.

Input is read from INFILE when given, otherwise from stdin.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import json
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


def has_union(query):
    """True when QUERY contains a top-level ``|`` union operator.

    Quoted string literals are skipped so ``//a[@x="a|b"]`` is not mistaken
    for a union.
    """
    quote = None
    for char in query:
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "|":
            return True
    return False


def read_stdin():
    data = sys.stdin.buffer.read()
    if isinstance(data, str):  # pragma: no cover - defensive
        data = data.encode("utf-8")
    return data


def read_file(path):
    """Read INFILE as UTF-8 text (an optional BOM is stripped)."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        die("xjq: error: could not read file %r: %s" % (path, reason))

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        die("xjq: error: could not read file %r: invalid utf-8: %s" % (path, exc))

    return text.encode("utf-8")


def read_input(path):
    """INFILE takes precedence over stdin whenever it is given."""
    return read_stdin() if path is None else read_file(path)


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
# JSON input support
# --------------------------------------------------------------------------

# XML 1.0 (5th ed.) Name production, minus ':' (lxml rejects colons in tags
# unless they resolve to a declared namespace prefix).
_NAME_START = (
    "A-Z_a-z"
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_CHAR = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile("^[%s][%s]*$" % (_NAME_START, _NAME_CHAR))

ITEM_TAG = "item"
ROOT_TAG = "root"

JSON_TYPES = (
    (type(None), "null"),
    (bool, "bool"),
    (int, "int"),
    (float, "float"),
    (str, "str"),
    (dict, "dict"),
    (list, "list"),
)


def looks_like_json(data):
    """True when the input's first non-space byte starts an object or array."""
    return data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"{", b"[")


def load_json(data):
    """Parse ``data`` as JSON, returning None when it is not a JSON container.

    Only top-level objects and arrays count as JSON input; top-level
    primitives fall through to the XML/HTML parser.
    """
    if not looks_like_json(data):
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def json_type(value):
    for kind, name in JSON_TYPES:
        if isinstance(value, kind):
            return name
    return "str"  # pragma: no cover - json never yields anything else


def json_text(value):
    """The element text for a JSON primitive (numbers in minimal form)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format_scalar(value)
    return value


def check_key(key):
    if not isinstance(key, str) or not _XML_NAME.match(key):
        die(
            "xjq: error: invalid json key %r: not a valid XML element name" % (key,)
        )
    return key


def build_element(tag, value):
    """Convert one JSON value into an annotated element named ``tag``."""
    try:
        element = etree.Element(tag)
    except ValueError:
        die("xjq: error: invalid json key %r: not a valid XML element name" % (tag,))

    kind = json_type(value)
    element.set("type", kind)

    if kind == "dict":
        for key, item in value.items():
            element.append(build_element(check_key(key), item))
    elif kind == "list":
        for item in value:
            element.append(build_element(ITEM_TAG, item))
    else:
        element.text = json_text(value)

    if len(element) == 0 and not element.text:
        element.text = ""  # keep empty elements from self-closing
    return element


def json_to_xml(value):
    """Wrap a JSON object/array in <root>, preserving key order."""
    root = etree.Element(ROOT_TAG)
    if isinstance(value, dict):
        for key, item in value.items():
            root.append(build_element(check_key(key), item))
    else:
        for item in value:
            root.append(build_element(ITEM_TAG, item))
    if len(root) == 0:
        root.text = ""
    return root


def expand_empty(node):
    """Give childless, textless elements an explicit empty text node."""
    if isinstance(node, etree._Element):
        for element in node.iter():
            if isinstance(element.tag, str) and len(element) == 0 and not element.text:
                element.text = ""
    return node


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


def serialize_xml(node, keep_empty_tags=False, compact=False):
    """Serialize a node as XML, pretty-printed unless ``compact`` is set.

    Either way the node is re-parsed with ``remove_blank_text`` so the layout
    of the source document does not leak into the output; ``compact`` then
    simply adds no indentation or line breaks of its own.

    ``keep_empty_tags`` re-expands childless elements to ``<a></a>`` instead of
    ``<a/>``; JSON-converted documents are written without self-closing tags.
    """
    pretty = not compact
    try:
        raw = etree.tostring(node, encoding="unicode", with_tail=False)
    except Exception:  # pragma: no cover - defensive
        return None

    if isinstance(node.tag, str):
        try:
            parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
            reparsed = etree.fromstring(raw.encode("utf-8"), parser)
            if keep_empty_tags:
                expand_empty(reparsed)
            return etree.tostring(
                reparsed, encoding="unicode", pretty_print=pretty, with_tail=False
            ).rstrip("\n")
        except etree.XMLSyntaxError:
            pass

    return etree.tostring(
        node, encoding="unicode", pretty_print=pretty, with_tail=False
    ).rstrip("\n")


def pretty_xml(node, keep_empty_tags=False):
    return serialize_xml(node, keep_empty_tags, compact=False)


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


def tag_name(element):
    """The element's name, without any namespace URI prefix."""
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def as_element(item):
    """Return ``item`` as an element, or None when it is not one.

    Comments and processing instructions are not elements for this purpose.
    """
    if isinstance(item, etree._ElementTree):
        item = item.getroot()
    if isinstance(item, etree._Element) and isinstance(item.tag, str):
        return item
    return None


def export_json(elements, compact=False):
    """Export elements as a JSON array of {tag_name: immediate_text} objects.

    Only the immediate text of each element is used; text belonging to child
    elements is left out.  ``compact`` selects a zero-indent JSON layout.
    """
    payload = [
        {tag_name(element): normalize(element_text(element, DIRECT))}
        for element in elements
    ]
    return json.dumps(payload, indent=0 if compact else 2, ensure_ascii=False)


def render(
    result,
    keep_empty_tags=False,
    first=False,
    compact=False,
    json_export=False,
    union=False,
):
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

    # --first keeps only the leading match, whatever its kind (text, attribute
    # value or XML node).  With no matches at all there is nothing to keep.
    if first:
        result = result[:1]

    elements = [as_element(item) for item in result]
    all_elements = all(element is not None for element in elements)

    # --json exports element results; anything auto-detected as text is left
    # alone, so a mixed or text-only result falls through to the rules below.
    if json_export and all_elements:
        return export_json(elements, compact), True

    # A union that matched both nodes and non-nodes is written as text.
    if union and not all_elements and any(e is not None for e in elements):
        lines = [normalize(element_text(item, DESCENDANT)) for item in result]
        return "\n".join(lines), False

    # An XML node result: emit only the first matching node.
    for item in result:
        if isinstance(item, (etree._Element, etree._ElementTree)):
            node = item.getroot() if isinstance(item, etree._ElementTree) else item
            return serialize_xml(node, keep_empty_tags, compact), True

    lines = [normalize(format_scalar(item)) for item in result]
    return "\n".join(lines), False


def build_parser():
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description=(
            "Query XML or JSON using XPath 1.0 or a CSS selector; input is read "
            "from INFILE when given, otherwise from stdin."
        ),
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression or CSS selector")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="read input from this file instead of stdin",
    )
    parser.add_argument(
        "ignored",
        metavar="...",
        nargs="*",
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
        help="extract the direct text of each matched element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="extract all descendant text of each matched element",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="export matched XML elements as JSON objects of {tag: text}",
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
        help="compact output: do not pretty-print XML results",
    )
    parser.add_argument(
        "-v", "--version", action="version", version="xjq 1.0",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    # --text-all wins when both are given.
    text_mode = DESCENDANT if args.text_all else (DIRECT if args.text else None)

    data = read_input(args.infile)
    document = load_json(data)
    if document is None:
        root, is_html = parse_document(data)
        is_json = False
    else:
        root, is_html, is_json = json_to_xml(document), False, True

    union = not args.css and has_union(args.query)

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
        if union and text_mode == DESCENDANT:
            # A union's descendant text is concatenated into a single output
            # string; --first keeps only the leading union match.
            matches = result[:1] if args.first else result
            result = normalize(" ".join(extract_text(matches, DESCENDANT)))
        else:
            result = extract_text(result, text_mode)

    # Output precedence: --text-all, then --text, then --json, then the
    # default auto-formatting.  --json never applies to a CSS query.
    json_export = args.json and not args.css and not text_mode

    output, is_block = render(
        result,
        keep_empty_tags=is_json,
        first=args.first,
        compact=args.compact,
        json_export=json_export,
        union=union,
    )

    if output:
        sys.stdout.write(output)
        if is_block:
            sys.stdout.write("\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # pragma: no cover
        sys.exit(0)
