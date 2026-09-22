#!/usr/bin/env python3
"""xjq - query XML/HTML/JSON with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import codecs
import copy
import json
import math
import re
import sys

import cssselect
from cssselect.parser import CombinedSelector as CssCombinedSelector
from cssselect.parser import Element as CssElement
from lxml import etree

PROG = "xjq.py"

# The custom pseudo-element this tool understands, e.g. `div::text`.
TEXT_PSEUDO_ELEMENT = "text"


def _fail(message):
    """Report an error on stderr and exit with status 1."""
    sys.stderr.write("{}: error: {}\n".format(PROG, message))
    sys.stderr.flush()
    raise SystemExit(1)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Query XML/HTML read from stdin using an XPath 1.0 expression "
            "or a CSS selector."
        ),
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
        help="extract the direct text of each matched element, one per element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="extract the descendant text of each matched element, one per element",
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
        help="compact output: serialize XML without added pretty-printing",
    )
    parser.add_argument(
        "query", metavar="QUERY", help="XPath expression, or CSS selector with --css"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="document to read; takes precedence over stdin",
    )
    # T33: trailing positionals are accepted and discarded, but an
    # unrecognized *option* is still an argparse error.
    parser.add_argument(
        "ignored",
        metavar="...",
        nargs="*",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def strip_bom(data):
    """Drop a leading UTF-8 byte-order mark (T32: allowed on either source)."""
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8) :]
    return data


def read_stdin():
    """Read the whole document from stdin as bytes, so lxml can honour the
    document's own encoding declaration."""
    try:
        data = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        data = sys.stdin.read().encode("utf-8", "replace")
    except OSError as exc:
        _fail("failed to read xml input from stdin: {}".format(exc))
    return strip_bom(data)


def read_file(path):
    """Read INFILE and decode it as UTF-8 text, tolerating a leading BOM.

    The decoded text is handed back as UTF-8 bytes so the parser sees a byte
    stream that matches the encoding the spec fixes for files (T30).  Anything
    that stops the bytes from being obtained or decoded is one failure: a
    message on stderr and exit `1` (T34).
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        _fail("failed to read input file {!r}: {}".format(path, reason))

    try:
        text = strip_bom(data).decode("utf-8")
    except UnicodeDecodeError:
        _fail("failed to read input file {!r}: not valid UTF-8 text".format(path))
    return text.encode("utf-8")


def read_input(infile):
    """Return the document bytes: INFILE when given, otherwise stdin."""
    if infile is not None:
        return read_file(infile)
    return read_stdin()


def parse_document(data):
    """Parse `data` as XML with case-sensitive element matching."""
    if not data.strip():
        _fail("failed to parse xml input: empty xml document")

    parser = etree.XMLParser(recover=False, resolve_entities=True)
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        _fail("failed to parse xml input: {}".format(exc))
    except ValueError as exc:
        _fail("failed to parse xml input: {}".format(exc))

    if root is None:
        _fail("failed to parse xml input: no root element found")
    return root.getroottree()


# ---------------------------------------------------------------------------
# JSON input
# ---------------------------------------------------------------------------

# The XML 1.0 (5th ed.) `Name` production with the colon removed: a converted
# key becomes a plain element name, never a namespace-qualified QName.
_NAME_START = (
    "A-Za-z_"
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd"
)
_NAME_CHAR = _NAME_START + "0-9\\-.\u00b7\u0300-\u036f\u203f-\u2040"
XML_NAME_RE = re.compile("[{}][{}]*\\Z".format(_NAME_START, _NAME_CHAR))

# The `type` attribute vocabulary, keyed by the Python type json.loads produces.
JSON_ROOT_TAG = "root"
JSON_ITEM_TAG = "item"


def is_valid_xml_name(name):
    """True when `name` can be used verbatim as an XML element name."""
    if not XML_NAME_RE.match(name):
        return False
    try:
        etree.Element(name)
    except ValueError:
        return False
    return True


def format_json_number(value):
    """Render a JSON number in its minimal string form.

    Integers print as-is; floats print with the shortest round-tripping form,
    except that an integral float drops its fractional part (`1.0 -> "1"`).
    """
    if isinstance(value, int):
        return str(value)
    if value == value and value not in (float("inf"), float("-inf")):
        if float(value).is_integer():
            return str(int(value))
    return repr(value)


def json_value_type(value):
    """The `type` attribute name for one decoded JSON value."""
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


def json_primitive_text(value):
    """The element text for a primitive JSON value; null renders as empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format_json_number(value)
    return value


def _build_json_element(parent, tag, value):
    """Create the element for `value` under `parent` and recurse into it."""
    element = etree.SubElement(parent, tag)
    element.set("type", json_value_type(value))
    if isinstance(value, dict):
        _fill_json_object(element, value)
    elif isinstance(value, list):
        _fill_json_array(element, value)
    else:
        element.text = json_primitive_text(value)
    if len(element) == 0 and not element.text:
        # Keep empty elements as a start/end tag pair rather than `<a/>`.
        element.text = ""
    return element


def _fill_json_object(parent, obj):
    """Append one child element per key, in source key order."""
    for key, value in obj.items():
        if not is_valid_xml_name(key):
            _fail(
                "invalid json input: json key {!r} is not a valid XML element "
                "name".format(key)
            )
        _build_json_element(parent, key, value)


def _fill_json_array(parent, entries):
    """Append one `<item>` child per array entry, in source order."""
    for value in entries:
        _build_json_element(parent, JSON_ITEM_TAG, value)


def json_to_xml(document):
    """Convert a decoded JSON object/array into an lxml tree rooted at `root`."""
    root = etree.Element(JSON_ROOT_TAG)
    if isinstance(document, dict):
        _fill_json_object(root, document)
    else:
        _fill_json_array(root, document)
    return root.getroottree()


def detect_json(data):
    """Decode `data` as a JSON object/array, or return None to use XML.

    Top-level JSON primitives are deliberately rejected: they are valid JSON
    but not valid JSON *input* for this mode, so they fall through to the XML
    parser along with everything else that fails detection.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        document = json.loads(text)
    except ValueError:
        return None
    if isinstance(document, (dict, list)):
        return document
    return None


def parse_input(data):
    """Auto-detect the input as JSON or XML/HTML and return the parsed tree."""
    document = detect_json(data)
    if document is not None:
        return json_to_xml(document)
    return parse_document(data)


CSS_PREFIX = "descendant-or-self::"


def _css_text_mode(selector):
    """Classify one parsed selector's `::text` usage.

    Returns None for a plain selector, "direct" for `sel::text` (the element's
    own text nodes) and "descendant" for `sel ::text` (every text node in the
    subtree).  Any other pseudo-element is rejected.
    """
    pseudo = selector.pseudo_element
    if pseudo is None:
        return None
    if str(pseudo) != TEXT_PSEUDO_ELEMENT:
        _fail(
            "invalid css selector: unsupported pseudo-element ::{}".format(pseudo)
        )

    tree = selector.parsed_tree
    # `sel ::text` parses as `sel` followed by a bare universal selector.
    if (
        isinstance(tree, CssCombinedSelector)
        and tree.combinator == " "
        and isinstance(tree.subselector, CssElement)
        and tree.subselector.element is None
        and tree.subselector.namespace is None
    ):
        return "descendant"
    return "direct"


def translate_css(query):
    """Translate a CSS selector (group) into an equivalent XPath expression."""
    translator = cssselect.GenericTranslator()
    try:
        selectors = cssselect.parse(query)
    except cssselect.SelectorError as exc:
        _fail("invalid css selector: {}".format(exc))
    except Exception as exc:  # pragma: no cover - cssselect internal failure
        _fail("invalid css selector: {}".format(exc))

    modes = [_css_text_mode(selector) for selector in selectors]
    if len(set(modes)) > 1:
        _fail(
            "invalid css selector: comma-separated selectors must all use the "
            "same ::text mode; do not mix `sel::text`, `sel ::text` and plain "
            "selectors in one query"
        )

    parts = []
    for selector, mode in zip(selectors, modes):
        try:
            expr = translator.xpath(selector.parsed_tree)
        except cssselect.SelectorError as exc:
            _fail("invalid css selector: {}".format(exc))
        if mode == "descendant":
            # The trailing universal step becomes the text-node test itself.
            expr.element = "text()"
            parts.append(CSS_PREFIX + str(expr))
        elif mode == "direct":
            parts.append(CSS_PREFIX + str(expr) + "/text()")
        else:
            parts.append(CSS_PREFIX + str(expr))
    return " | ".join(parts)


def evaluate(tree, query):
    """Evaluate an XPath 1.0 expression against the parsed document."""
    try:
        return tree.xpath(query)
    except (etree.XPathError, etree.LxmlError) as exc:
        _fail("invalid xpath expression: {}".format(exc))
    except (ValueError, TypeError) as exc:
        _fail("invalid xpath expression: {}".format(exc))


def normalize(text):
    """Strip a result and collapse internal whitespace runs to single spaces."""
    return " ".join(text.split())


def format_number(value):
    """Render a number using XPath 1.0 string() conventions."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value):
        return str(int(value))
    return repr(value)


def to_text(value):
    """Render one non-node result as text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _drop_ignorable_whitespace(element):
    """Remove whitespace-only text and tails so pretty-printing can re-indent."""
    for node in element.iter():
        if (
            isinstance(node.tag, str)
            and len(node)
            and node.text is not None
            and not node.text.strip()
        ):
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None


def serialize_node(node, compact=False):
    """Serialize a single node as XML.

    The default is pretty-printed: whitespace-only text and tails are dropped
    first so the serializer can re-indent the subtree from column zero.
    `compact` withholds that whole pipeline instead (T28) - the node's own
    character data is left exactly as it was and no indentation, line breaks
    or trailing newline are added (T29).
    """
    clone = copy.deepcopy(node)
    clone.tail = None
    if compact:
        return etree.tostring(
            clone, pretty_print=False, encoding="unicode", with_tail=False
        )
    _drop_ignorable_whitespace(clone)
    return etree.tostring(
        clone, pretty_print=True, encoding="unicode", with_tail=False
    )


def direct_text(element):
    """Concatenate an element's direct text-node children (`el/text()`)."""
    parts = [element.text or ""]
    parts.extend(child.tail or "" for child in element)
    return "".join(parts)


def descendant_text(element):
    """The element's XPath string-value: every descendant text node, joined."""
    return element.xpath("string(.)")


def render(result, text_mode=None, first=False, compact=False):
    """Turn an XPath result into the bytes to write to stdout.

    `text_mode` is None, "direct" (--text) or "all" (--text-all).  It only ever
    applies to element results: anything the query already reduced to a string,
    number or boolean has no text left to extract, which is what makes the
    flags no-ops over `text()` and `::text` queries.

    `first` (--first) truncates the result sequence before the text/node branch
    is chosen, so it covers text, attribute and XML-node results alike (T26).
    `compact` (--compact) only reaches XML serialization.
    """
    if not isinstance(result, list):
        result = [result]

    if first:
        result = result[:1]

    if not result:
        return b""

    if text_mode:
        lines = []
        for item in result:
            if isinstance(item, etree._Element):
                extract = direct_text if text_mode == "direct" else descendant_text
                lines.append(normalize(extract(item)))
            else:
                lines.append(normalize(to_text(item)))
        return "\n".join(lines).encode("utf-8")

    nodes = [item for item in result if isinstance(item, etree._Element)]
    if nodes:
        # Only the first node is emitted when several match.
        return serialize_node(nodes[0], compact).encode("utf-8")

    lines = [normalize(to_text(item)) for item in result]
    return "\n".join(lines).encode("utf-8")


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    # --text-all wins when both text modifiers are given.
    text_mode = "all" if args.text_all else ("direct" if args.text else None)

    data = read_input(args.infile)
    tree = parse_input(data)
    query = translate_css(args.query) if args.css else args.query
    result = evaluate(tree, query)

    payload = render(result, text_mode, args.first, args.compact)
    if payload:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
