#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Reads the document from stdin, evaluates QUERY against it and prints the
result.  INFILE is accepted for compatibility but ignored.
"""

import argparse
import copy
import os
import re
import sys

from lxml import etree

import cssselect
from cssselect.parser import (
    CombinedSelector,
    Element,
    Selector,
    SelectorError,
)
from cssselect.xpath import GenericTranslator, HTMLTranslator


PROG = "xjq"

# Name of the custom pseudo-element used for text extraction in CSS queries.
TEXT_PSEUDO = "text"


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML read from stdin using XPath 1.0 or a CSS selector.",
    )
    parser.add_argument(
        "query", metavar="QUERY", help="XPath expression or CSS selector to evaluate"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted but ignored; input is always read from stdin",
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
        help="print the direct text of every matched element, one per line",
    )
    parser.add_argument(
        "--text-all",
        dest="text_all",
        action="store_true",
        help="print all descendant text of every matched element, one per line",
    )
    return parser


def parse_args(argv):
    parser = build_parser()
    # Be lenient about unrecognised options: they are ignored rather than fatal.
    args, extra = parser.parse_known_args(argv)
    if args.infile is None:
        for item in extra:
            if not item.startswith("-"):
                args.infile = item
                break
    return args


def read_stdin():
    data = sys.stdin.buffer.read()
    if isinstance(data, str):  # pragma: no cover - defensive
        data = data.encode("utf-8")
    return data


def looks_like_html(data):
    head = data[:2048].decode("utf-8", "replace").lower()
    return "<!doctype html" in head or "<html" in head


def parse_document(data):
    """Parse *data* as XML, falling back to HTML for HTML documents."""
    if data is None or not data.strip():
        die("%s: error: could not parse xml input: document is empty" % PROG)

    # Strip a UTF-8 BOM, it upsets the parser.
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]

    xml_error = None
    try:
        parser = etree.XMLParser(
            remove_blank_text=True,
            resolve_entities=False,
            recover=False,
            huge_tree=True,
        )
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        xml_error = exc

    if looks_like_html(data):
        try:
            parser = etree.HTMLParser(remove_blank_text=True, huge_tree=True)
            root = etree.fromstring(data, parser)
            if root is not None and len(root) or root is not None and root.text:
                return root
        except etree.XMLSyntaxError:
            pass

    die("%s: error: could not parse xml input: %s" % (PROG, xml_error))


def strip_namespaces(root):
    """Return a copy of the tree with all namespaces removed."""
    clone = copy.deepcopy(root)
    for node in clone.iter():
        if isinstance(node.tag, str) and "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
        for name in list(node.attrib):
            if "}" in name:
                value = node.attrib.pop(name)
                node.attrib[name.split("}", 1)[1]] = value
    etree.cleanup_namespaces(clone)
    return clone


def has_namespaces(root):
    for node in root.iter():
        if isinstance(node.tag, str) and node.tag.startswith("{"):
            return True
    return False


def evaluate(root, query):
    try:
        result = root.xpath(query)
    except etree.XPathError as exc:
        die("%s: error: invalid xpath expression %r: %s" % (PROG, query, exc))
    except (TypeError, ValueError) as exc:
        die("%s: error: invalid xpath expression %r: %s" % (PROG, query, exc))

    if is_empty(result) and has_namespaces(root):
        # Convenience: retry against a namespace-free view of the document so
        # that plain names such as //title match namespaced documents too.
        try:
            retry = strip_namespaces(root).xpath(query)
        except etree.XPathError:
            retry = None
        except (TypeError, ValueError):
            retry = None
        if retry is not None and not is_empty(retry):
            return retry
    return result


def is_empty(result):
    return isinstance(result, list) and not result


def is_descendant_text(tree):
    """True for the ``selector ::text`` form (a bare universal descendant)."""
    return (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and isinstance(tree.subselector, Element)
        and tree.subselector.element is None
        and tree.subselector.namespace is None
    )


def compile_css(query, html=False):
    """Translate a CSS selector into XPath.

    Returns a ``(xpath, mode)`` pair where *mode* is ``None`` (plain node
    query), ``"direct"`` for ``selector::text`` or ``"descendant"`` for
    ``selector ::text``.
    """
    translator = HTMLTranslator() if html else GenericTranslator()

    try:
        selectors = cssselect.parse(query)
    except SelectorError as exc:
        die("%s: error: invalid css selector %r: %s" % (PROG, query, exc))
    except Exception as exc:  # pragma: no cover - defensive
        die("%s: error: invalid css selector %r: %s" % (PROG, query, exc))

    if not selectors:
        die("%s: error: invalid css selector %r: empty selector" % (PROG, query))

    modes = []
    paths = []
    for selector in selectors:
        pseudo = selector.pseudo_element
        tree = selector.parsed_tree
        if pseudo is None:
            mode = None
        elif isinstance(pseudo, str) and pseudo == TEXT_PSEUDO:
            if is_descendant_text(tree):
                # `foo ::text`: every text node below (and inside) the match.
                mode = "descendant"
                tree = tree.selector
            else:
                mode = "direct"
        else:
            name = getattr(pseudo, "name", pseudo)
            die(
                "%s: error: invalid css selector %r: unsupported pseudo-element %r"
                % (PROG, query, "::%s" % name)
            )

        try:
            path = translator.selector_to_xpath(
                Selector(tree, None), prefix="descendant-or-self::"
            )
        except SelectorError as exc:
            die("%s: error: invalid css selector %r: %s" % (PROG, query, exc))
        if mode == "descendant":
            path += "/descendant-or-self::text()"

        modes.append(mode)
        paths.append(path)

    unique = set(modes)
    if len(unique) > 1:
        if unique == {"direct", "descendant"}:
            reason = "cannot mix 'selector::text' and 'selector ::text'"
        else:
            reason = "cannot mix '::text' and plain selectors"
        die("%s: error: invalid css selector %r: %s" % (PROG, query, reason))

    return " | ".join(paths), modes[0]


def collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def format_number(value):
    if value != value:  # NaN
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def serialize_node(node):
    if isinstance(node, etree._Element):
        clone = copy.deepcopy(node)
        clone.tail = None
        try:
            etree.indent(clone, space="  ")
        except Exception:  # pragma: no cover - older lxml
            pass
        text = etree.tostring(
            clone, pretty_print=True, with_tail=False, encoding="unicode"
        )
        return text.rstrip("\n")
    # Comments / processing instructions / entity refs
    return etree.tostring(node, with_tail=False, encoding="unicode").rstrip("\n")


def node_to_text(node):
    if isinstance(node, etree._Element):
        return "".join(node.itertext())
    return str(node)


def direct_text(element):
    """The text of *element* excluding the text of its descendants."""
    parts = [element.text or ""]
    for child in element:
        parts.append(child.tail or "")
    return "".join(parts)


def extract_text(result, all_text):
    """Replace the elements of *result* by their text, one entry per element.

    Results that do not hold nodes (numbers, booleans, or text produced by the
    query itself) are returned unchanged, which makes --text/--text-all no-op
    modifiers for queries that already extract text.
    """
    if not isinstance(result, list):
        return result

    values = []
    for item in result:
        if isinstance(item, etree._Element):
            values.append(node_to_text(item) if all_text else direct_text(item))
        elif isinstance(item, (bytes, bytearray)):
            values.append(item.decode("utf-8", "replace"))
        else:
            values.append(str(item))
    return values


def render(result):
    """Turn an XPath result into the string to print (or None for no output)."""
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, float) or isinstance(result, int):
        return format_number(float(result))
    if isinstance(result, (bytes, bytearray)):
        return collapse(result.decode("utf-8", "replace")) or None
    if isinstance(result, str):
        return collapse(result) or None

    if not isinstance(result, list):  # pragma: no cover - defensive
        return collapse(str(result)) or None

    if not result:
        return None

    # An element (or comment / PI) result is serialized XML: first node only.
    first = result[0]
    if isinstance(first, etree._Element) or isinstance(
        first, (etree._Comment, etree._ProcessingInstruction, etree._Entity)
    ):
        return serialize_node(first)

    lines = []
    for item in result:
        if isinstance(item, etree._Element):
            value = node_to_text(item)
        elif isinstance(item, (bytes, bytearray)):
            value = item.decode("utf-8", "replace")
        else:
            value = str(item)
        value = collapse(value)
        if value:
            lines.append(value)

    if not lines:
        return None
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        data = read_stdin()
    except OSError as exc:
        die("%s: error: could not read xml input: %s" % (PROG, exc))

    root = parse_document(data)

    # --text-all wins when both text flags are given.
    text_mode = "all" if args.text_all else ("direct" if args.text else None)

    if args.css:
        query, css_mode = compile_css(args.query, looks_like_html(data))
        result = evaluate(root, query)
        if css_mode == "direct":
            result = extract_text(result, all_text=False)
        elif css_mode is None and text_mode is not None:
            result = extract_text(result, all_text=text_mode == "all")
    else:
        result = evaluate(root, args.query)
        if text_mode is not None:
            result = extract_text(result, all_text=text_mode == "all")

    output = render(result)

    if output:
        try:
            sys.stdout.write(output)
            sys.stdout.flush()
        except BrokenPipeError:  # e.g. piped into `head`
            try:
                sys.stdout.close()
            except Exception:
                pass
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
