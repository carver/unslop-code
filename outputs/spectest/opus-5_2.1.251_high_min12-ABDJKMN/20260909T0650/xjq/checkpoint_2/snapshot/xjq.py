#!/usr/bin/env python3
"""xjq -- XPath/CSS querying of XML read from stdin.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

QUERY is an XPath 1.0 expression, or a CSS selector when --css is given. INFILE
is accepted for compatibility but is never read: the document always comes from
stdin.

Text extraction has two modes, spelled either as a flag or as the custom
``::text`` pseudo-element in a CSS selector:

    direct       -t / --text    ``sel::text``    the element's own text nodes
    descendant   --text-all     ``sel ::text``   every descendant text node
"""

import argparse
import copy
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


class CSSModeError(Exception):
    """Comma-separated CSS selectors disagree about their ::text mode."""


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


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML read from stdin with XPath 1.0 or a CSS selector.",
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
        "query", metavar="QUERY", help="XPath expression, or CSS selector with --css"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility; ignored (input is read from stdin)",
    )
    return parser.parse_args(argv)


def read_stdin():
    """Read the whole document from stdin as bytes."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read()
    return sys.stdin.read().encode("utf-8", "replace")


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


def serialize_node(node):
    """Pretty-print a single node as XML."""
    if isinstance(node, etree._ElementTree):
        node = node.getroot()
        if node is None:
            return ""
    node = copy.deepcopy(node)
    node.tail = None
    try:
        etree.indent(node, space=INDENT)
    except (TypeError, ValueError):
        pass
    return etree.tostring(
        node, pretty_print=True, with_tail=False, encoding="unicode"
    )


def render(result):
    """Turn an XPath result into the exact text to write to stdout."""
    if isinstance(result, list):
        if not result:
            return ""
        if is_node(result[0]):
            # Multiple XML nodes: only the first one is emitted.
            return serialize_node(result[0])
        lines = [normalize(to_text(item)) for item in result]
        return "".join(line + "\n" for line in lines)

    if is_node(result):
        return serialize_node(result)
    return normalize(to_text(result)) + "\n"


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

    data = read_stdin()

    try:
        root = parse_document(data)
    except etree.XMLSyntaxError as exc:
        return fail("could not parse xml input: %s" % exc)
    except (etree.LxmlError, ValueError) as exc:
        return fail("could not parse xml input: %s" % exc)
    if root is None:
        return fail("could not parse xml input: document is empty")

    try:
        result = query(root)
    except etree.XPathError as exc:
        return fail("invalid xpath expression %r: %s" % (args.query, exc))

    result = extract_text(result, text_mode)

    output = render(result)
    if output:
        sys.stdout.write(output)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(EXIT_ERROR)
    except KeyboardInterrupt:
        sys.exit(130)
