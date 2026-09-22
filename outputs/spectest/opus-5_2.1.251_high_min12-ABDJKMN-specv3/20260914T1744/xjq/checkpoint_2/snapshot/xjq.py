#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]
"""

import argparse
import copy
import math
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
        "query", metavar="QUERY", help="XPath expression, or CSS selector with --css"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted for compatibility but not used; input is always stdin",
    )
    return parser.parse_args(argv)


def read_stdin():
    """Read the whole document from stdin as bytes, so lxml can honour the
    document's own encoding declaration."""
    try:
        data = sys.stdin.buffer.read()
    except (AttributeError, ValueError):
        data = sys.stdin.read().encode("utf-8", "replace")
    except OSError as exc:
        _fail("failed to read xml input from stdin: {}".format(exc))
    return data


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
        if isinstance(node.tag, str) and node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None


def serialize_node(node):
    """Pretty-print a single node as XML."""
    clone = copy.deepcopy(node)
    clone.tail = None
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


def render(result, text_mode=None):
    """Turn an XPath result into the bytes to write to stdout.

    `text_mode` is None, "direct" (--text) or "all" (--text-all).  It only ever
    applies to element results: anything the query already reduced to a string,
    number or boolean has no text left to extract, which is what makes the
    flags no-ops over `text()` and `::text` queries.
    """
    if not isinstance(result, list):
        result = [result]

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
        return serialize_node(nodes[0]).encode("utf-8")

    lines = [normalize(to_text(item)) for item in result]
    return "\n".join(lines).encode("utf-8")


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    # --text-all wins when both text modifiers are given.
    text_mode = "all" if args.text_all else ("direct" if args.text else None)

    data = read_stdin()
    tree = parse_document(data)
    query = translate_css(args.query) if args.css else args.query
    result = evaluate(tree, query)

    payload = render(result, text_mode)
    if payload:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
