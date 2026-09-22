#!/usr/bin/env python3
"""xjq -- XPath/CSS querying of XML read from a file or stdin.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

QUERY is an XPath 1.0 expression, or a CSS selector when --css is given. The
document comes from INFILE when one is given -- decoded as UTF-8, with an
optional leading BOM -- and from stdin otherwise; any further positional
arguments are ignored.

Input is auto-detected: a document that parses as a JSON object or array is
converted to XML (wrapped in ``<root>``, every element tagged with its JSON
``type``) and queried as such; anything else is parsed as XML/HTML.

``--first`` trims the result to one; ``--compact`` serializes XML nodes without
added pretty-print formatting.

Text extraction has two modes, spelled either as a flag or as the custom
``::text`` pseudo-element in a CSS selector:

    direct       -t / --text    ``sel::text``    the element's own text nodes
    descendant   --text-all     ``sel ::text``   every descendant text node
"""

import argparse
import copy
import json
import math
import re
import sys

from cssselect import ExpressionError, GenericTranslator, SelectorError
from cssselect import parse as css_parse
from cssselect.parser import CombinedSelector
from cssselect.parser import Element as CSSElement
from cssselect.xpath import XPathExpr
from lxml import etree

PROG = "xjq.py"

EXIT_OK = 0
EXIT_ERROR = 1

INDENT = "  "

UTF8_BOM = b"\xef\xbb\xbf"

_WHITESPACE_RUN = re.compile(r"\s+")

# The two text-extraction modes, and the XPath step each one appends to a
# matched element.
TEXT_DIRECT = "direct"
TEXT_ALL = "all"

TEXT_STEP = {
    TEXT_DIRECT: "text()",
    TEXT_ALL: "descendant-or-self::*/text()",
}

TEXT_PSEUDO = "text"

# JSON conversion.
JSON_ROOT_TAG = "root"
JSON_ITEM_TAG = "item"
JSON_TYPE_ATTR = "type"
JSON_NULL_TYPE = "null"


class JSONKeyError(Exception):
    """A JSON key that cannot be used as an XML element name."""


class CSSModeError(Exception):
    """Comma-separated CSS selectors disagree about their ::text mode."""


class InputError(Exception):
    """INFILE could not be read, or is not UTF-8 text."""


class TextTranslator(GenericTranslator):
    """cssselect's XML translator plus the custom ``::text`` pseudo-element.

    ``sel::text`` becomes ``sel/text()``; ``sel ::text`` parses as a descendant
    combinator into the universal selector, so the same rule yields
    ``sel/descendant-or-self::*/text()`` -- every descendant text node.
    """

    def xpath_pseudo_element(self, xpath, pseudo_element):
        if pseudo_element != TEXT_PSEUDO:
            raise ExpressionError(
                "the pseudo-element ::%s is not supported" % (pseudo_element,)
            )
        path = str(xpath)
        if path == "*":
            # A bare `::text`: every text node.
            path = "text()"
        elif path.endswith("::*/*"):
            # `sel ::text`: cssselect turned the descendant combinator into
            # `.../descendant-or-self::*/*`; collapse that tail into a
            # descendant text-node step rather than descending one level too
            # far.
            path = path[:-3] + "text()"
        else:
            path = path + "/text()"
        return XPathExpr(path=path, element="")


def selector_text_mode(selector):
    """Text mode of one parsed CSS selector: None, TEXT_DIRECT or TEXT_ALL."""
    pseudo = selector.pseudo_element
    if pseudo is None:
        return None
    if pseudo != TEXT_PSEUDO:
        raise ExpressionError(
            "the pseudo-element ::%s is not supported" % (pseudo,)
        )
    tree = selector.parsed_tree
    if isinstance(tree, CombinedSelector) and tree.combinator == " ":
        sub = tree.subselector
        if (
            isinstance(sub, CSSElement)
            and sub.element is None
            and sub.namespace is None
        ):
            return TEXT_ALL
    return TEXT_DIRECT


def translate_css(query):
    """Translate a CSS selector list into (xpath, text mode).

    Raises SelectorError for an invalid selector and CSSModeError when the
    comma-separated parts do not all use the same ::text mode.
    """
    selectors = css_parse(query)
    modes = [selector_text_mode(selector) for selector in selectors]
    if len(set(modes)) > 1:
        raise CSSModeError(
            "mixed css query %r: comma-separated selectors must all use the "
            "same ::text mode (direct `sel::text`, descendant `sel ::text`, "
            "or no text extraction)" % query
        )
    translator = TextTranslator()
    paths = [
        translator.selector_to_xpath(selector, translate_pseudo_elements=True)
        for selector in selectors
    ]
    return " | ".join(paths), modes[0]


def extract_text(result, mode):
    """Replace each matched element with its text nodes, per `mode`.

    Results that are not elements (attribute/text strings, numbers, booleans,
    comments, PIs) pass through untouched, which is what makes `--text` and
    `--text-all` no-ops for a query that already extracts text.
    """
    if mode is None or not isinstance(result, list):
        return result
    step = TEXT_STEP[mode]
    out = []
    for item in result:
        if isinstance(item, etree._Element) and isinstance(item.tag, str):
            out.extend(item.xpath(step))
        else:
            out.append(item)
    return out


def detect_json(data):
    """Return the parsed JSON document, or None if this is not JSON input.

    Detection is a full parse of the whole input (T19): only a document that
    parses cleanly *and* yields an object or an array is JSON. Top-level
    primitives and anything malformed return None and fall back to XML.
    """
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(document, (dict, list)):
        return document
    return None


def json_type_name(value):
    """The `type` attribute for a JSON value: Python's name, `null` for None."""
    if value is None:
        return JSON_NULL_TYPE
    return type(value).__name__


def json_number_text(value):
    """Minimal string form of a JSON number (T20).

    Integral values -- including floats written as `1.0` or `1E2` -- print as
    integers; everything else uses Python's shortest round-trip repr, which
    drops the trailing zeros of `1.50` and keeps `0.00012` unexponentiated.
    """
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    return repr(value)


def json_text(value):
    """Element text for a JSON primitive; None when the element has no text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json_number_text(value)
    return value


def make_json_element(tag, value):
    """Build the element for `value` under `tag`, raising on an unusable tag."""
    if not isinstance(tag, str) or "{" in tag or "}" in tag:
        # `{ns}name` is lxml's namespace spelling, not an element name (T23).
        raise JSONKeyError(tag)
    try:
        element = etree.Element(tag)
    except (ValueError, TypeError):
        raise JSONKeyError(tag)
    element.set(JSON_TYPE_ATTR, json_type_name(value))
    return element


def fill_json_element(element, value):
    """Recursively populate `element` from the JSON `value`."""
    if isinstance(value, dict):
        for key, child_value in value.items():
            child = make_json_element(key, child_value)
            element.append(child)
            fill_json_element(child, child_value)
    elif isinstance(value, list):
        for entry in value:
            child = make_json_element(JSON_ITEM_TAG, entry)
            element.append(child)
            fill_json_element(child, entry)
    else:
        text = json_text(value)
        if text:
            # Empty text (null, and the empty string) leaves no text node at
            # all, so both serialize as an empty element (T26).
            element.text = text


def json_to_xml(document):
    """Convert a JSON object/array into an XML tree wrapped in `<root>`.

    `<root>` deliberately carries no `type`; every other element does.
    """
    root = etree.Element(JSON_ROOT_TAG)
    fill_json_element(root, document)
    return root


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML from INFILE or stdin with XPath 1.0 or a CSS selector.",
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
        help="extract direct text from matched elements",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        dest="text_all",
        help="extract descendant text from matched elements (wins over --text)",
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
        help="document to query; stdin is used when INFILE is omitted",
    )
    parser.add_argument(
        "ignored",
        metavar="...",
        nargs="*",
        help=argparse.SUPPRESS,  # extra positional arguments are ignored
    )
    return parser.parse_args(argv)


def strip_bom(data):
    """Drop a leading UTF-8 BOM, which is allowed on any input (T30)."""
    if data.startswith(UTF8_BOM):
        return data[len(UTF8_BOM) :]
    return data


def read_stdin():
    """Read the whole document from stdin as bytes."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        data = buffer.read()
    else:
        data = sys.stdin.read().encode("utf-8", "replace")
    return strip_bom(data)


def read_infile(path):
    """Read INFILE as UTF-8 text, returning its BOM-free UTF-8 bytes.

    The bytes (not the decoded text) are what the parsers see, so an XML
    document may still carry an `encoding="UTF-8"` declaration. A file that
    cannot be opened or is not valid UTF-8 raises InputError (T31).
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise InputError(
            "could not read file %r: %s" % (path, exc.strerror or exc)
        )
    data = strip_bom(data)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("could not decode file %r as utf-8: %s" % (path, exc))
    return data


def read_input(path):
    """The document bytes: INFILE when given, stdin otherwise (T27)."""
    if path is None:
        return read_stdin()
    return read_infile(path)


def parse_document(data):
    """Parse `data` as XML with case-sensitive, non-recovering parsing.

    Element and attribute names keep the case they were written with, and
    anything that is not well formed (including empty input) raises.
    """
    parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
    return etree.fromstring(data, parser)


def compile_query(query):
    return etree.XPath(query)


def is_node(value):
    """True for results lxml represents as nodes (elements, comments, PIs)."""
    return isinstance(value, (etree._Element, etree._ElementTree))


def format_number(value):
    """XPath 1.0 string() conversion for a number."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == int(value):
        return str(int(value))
    return repr(float(value))


def to_text(value):
    """Render a non-node XPath result as its string value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return format_number(float(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def normalize(text):
    """Strip, then collapse internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def serialize_node(node, compact=False):
    """Serialize a single node as XML, pretty-printed unless `compact`.

    Compact output adds no formatting of its own: whitespace already in the
    document survives, nothing is indented, and the node is followed by a single
    newline so it is still one line of output (T33).
    """
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
        if node is None:
            return ""
    node = copy.deepcopy(node)
    node.tail = None
    if compact:
        return etree.tostring(node, with_tail=False, encoding="unicode") + "\n"
    try:
        etree.indent(node, space=INDENT)
    except (TypeError, ValueError):
        pass
    return etree.tostring(
        node, pretty_print=True, with_tail=False, encoding="unicode"
    )


def render(result, first=False, compact=False):
    """Turn an XPath result into the exact text to write to stdout.

    `first` keeps only the first result, which for XML nodes is what the
    node-output rule already does (T34); `compact` drops the pretty-printing of
    node output and leaves every other output mode alone.
    """
    if isinstance(result, list):
        if not result:
            # No matches: silent, with or without --first.
            return ""
        if is_node(result[0]):
            # Multiple XML nodes: only the first one is emitted.
            return serialize_node(result[0], compact)
        lines = [normalize(to_text(item)) for item in result]
        if first:
            lines = lines[:1]
        return "".join(line + "\n" for line in lines)

    if is_node(result):
        return serialize_node(result, compact)
    return normalize(to_text(result)) + "\n"


def finish(root, query, text_mode, first=False, compact=False):
    """Run the compiled query against `root` and write the rendered result."""
    try:
        result = query(root)
    except etree.XPathError as exc:
        return fail("invalid xpath expression: %s" % (exc,))

    # --first trims the results the user would see, i.e. after text extraction
    # has turned matched elements into text nodes (T32).
    result = extract_text(result, text_mode)

    output = render(result, first, compact)
    if output:
        sys.stdout.write(output)
    return EXIT_OK


def fail(message):
    sys.stderr.write("%s: error: %s\n" % (PROG, message))
    return EXIT_ERROR


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # --text-all wins when both text flags are present.
    text_mode = TEXT_ALL if args.text_all else (TEXT_DIRECT if args.text else None)

    expression = args.query
    if args.css:
        try:
            expression, query_mode = translate_css(args.query)
        except CSSModeError as exc:
            return fail(str(exc))
        except SelectorError as exc:
            return fail("invalid css selector %r: %s" % (args.query, exc))
        if query_mode is not None:
            # The query already extracts text; the flags are no-ops.
            text_mode = None

    try:
        query = compile_query(expression)
    except etree.XPathError as exc:
        return fail("invalid xpath expression %r: %s" % (args.query, exc))

    try:
        data = read_input(args.infile)
    except InputError as exc:
        return fail(str(exc))

    document = detect_json(data)
    if document is not None:
        try:
            root = json_to_xml(document)
        except JSONKeyError as exc:
            return fail(
                "invalid json key %r: not a valid xml element name" % (str(exc),)
            )
        return finish(root, query, text_mode, args.first, args.compact)

    try:
        root = parse_document(data)
    except etree.XMLSyntaxError as exc:
        return fail("could not parse xml input: %s" % exc)
    except (etree.LxmlError, ValueError) as exc:
        return fail("could not parse xml input: %s" % exc)
    if root is None:
        return fail("could not parse xml input: document is empty")

    return finish(root, query, text_mode, args.first, args.compact)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(EXIT_ERROR)
    except KeyboardInterrupt:
        sys.exit(130)
