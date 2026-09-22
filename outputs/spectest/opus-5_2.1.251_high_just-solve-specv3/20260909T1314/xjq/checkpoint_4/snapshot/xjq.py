#!/usr/bin/env python3
"""xjq - query XML/HTML/JSON with XPath 1.0 or CSS selectors.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

Reads the document from INFILE (or from stdin when no file is given),
evaluates QUERY against it and prints the result.
"""

import argparse
import copy
import json
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

# Byte-order mark allowed at the start of a UTF-8 document.
BOM_UTF8 = b"\xef\xbb\xbf"

# Name of the custom pseudo-element used for text extraction in CSS queries.
TEXT_PSEUDO = "text"

# Tag wrapping a document converted from JSON, and the tag used for the
# entries of a JSON array (arrays have no keys to name their children after).
JSON_ROOT_TAG = "root"
JSON_ITEM_TAG = "item"

# XML 1.0 (fifth edition) NCName production: an element name without a colon,
# which is what a JSON key has to look like to become a tag name.
_NAME_START = (
    ":A-Z_a-z"
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd"
)
_NAME_CHAR = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
XML_NAME_RE = re.compile(
    "^[%s][%s]*$" % (_NAME_START.replace(":", ""), _NAME_CHAR.replace(":", ""))
)


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Query XML/HTML/JSON from INFILE (or stdin) using XPath 1.0 "
            "or a CSS selector."
        ),
    )
    parser.add_argument(
        "query", metavar="QUERY", help="XPath expression or CSS selector to evaluate"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="file to read the document from; defaults to stdin",
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
        help="compact output: do not pretty-print serialized xml",
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


def read_file(path):
    """Read *path* as UTF-8 text (an optional BOM is stripped).

    A missing or otherwise unreadable file is a fatal error (exit code 1).
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        die("%s: error: could not read %s: %s" % (PROG, path, reason))

    if data.startswith(BOM_UTF8):
        data = data[len(BOM_UTF8):]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        die("%s: error: could not read %s: %s" % (PROG, path, exc))
    # Hand the parsers plain UTF-8 bytes again: lxml refuses str input that
    # carries an encoding declaration.
    return text.encode("utf-8")


def read_input(infile):
    """Read the document: INFILE takes precedence over stdin."""
    if infile is not None:
        return read_file(infile)
    try:
        return read_stdin()
    except OSError as exc:
        die("%s: error: could not read xml input: %s" % (PROG, exc))


def looks_like_html(data):
    head = data[:2048].decode("utf-8", "replace").lower()
    return "<!doctype html" in head or "<html" in head


def json_type(value):
    """Return the ``type`` attribute for a converted JSON *value*."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    # json.loads never produces anything else.
    die("%s: error: invalid json input: unsupported value %r" % (PROG, value))


def json_number_text(value):
    """The minimal string form of a JSON number (1.0 -> '1', 1.50 -> '1.5')."""
    if isinstance(value, int):
        return str(value)
    if value != value:  # NaN
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    if value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def json_primitive_text(value):
    """The element text for a JSON primitive; null becomes the empty string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json_number_text(value)
    return value


def json_child(parent, key):
    """Create a child element of *parent* named after the JSON key *key*."""
    if not isinstance(key, str) or not XML_NAME_RE.match(key):
        die(
            "%s: error: invalid json input: key %r is not a valid xml element name"
            % (PROG, key)
        )
    try:
        return etree.SubElement(parent, key)
    except ValueError:  # pragma: no cover - defensive, the regex catches these
        die(
            "%s: error: invalid json input: key %r is not a valid xml element name"
            % (PROG, key)
        )


def json_fill(element, value):
    """Populate *element* (type attribute, children or text) from *value*."""
    kind = json_type(value)
    element.set("type", kind)
    # An empty string keeps lxml from emitting a self-closing tag.
    element.text = ""
    if kind == "dict":
        for key, item in value.items():
            json_fill(json_child(element, key), item)
    elif kind == "list":
        for item in value:
            json_fill(etree.SubElement(element, JSON_ITEM_TAG), item)
    else:
        element.text = json_primitive_text(value)


def json_to_xml(value):
    """Convert a JSON object/array into a ``<root>`` element tree."""
    root = etree.Element(JSON_ROOT_TAG)
    root.text = ""
    if isinstance(value, dict):
        # Top-level object: every key becomes a direct child of <root>.
        for key, item in value.items():
            json_fill(json_child(root, key), item)
    else:
        # Top-level array: every entry becomes an <item> child of <root>.
        for item in value:
            json_fill(etree.SubElement(root, JSON_ITEM_TAG), item)
    return root


def detect_json(data):
    """Return the parsed JSON object/array in *data*, or None if it is not one.

    Only objects and arrays count as JSON input; top-level primitives (and
    anything that does not parse) fall back to the XML/HTML parser.
    """
    if not data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if isinstance(value, (dict, list)):
        return value
    return None


def build_document(data):
    """Turn raw stdin bytes into an element tree.

    JSON objects and arrays are converted to XML; everything else (including
    top-level JSON primitives) is parsed as XML/HTML.
    """
    if data is not None and data.startswith(BOM_UTF8):
        data = data[len(BOM_UTF8):]

    value = detect_json(data)
    if value is not None:
        return json_to_xml(value)
    return parse_document(data)


def parse_document(data):
    """Parse *data* as XML, falling back to HTML for HTML documents."""
    if data is None or not data.strip():
        die("%s: error: could not parse xml input: document is empty" % PROG)

    # Strip a UTF-8 BOM, it upsets the parser.
    if data.startswith(BOM_UTF8):
        data = data[len(BOM_UTF8):]

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


def serialize_node(node, compact=False):
    if isinstance(node, etree._Element):
        clone = copy.deepcopy(node)
        clone.tail = None
        if compact:
            # Compact mode adds no formatting of its own.
            text = etree.tostring(clone, with_tail=False, encoding="unicode")
            return text.rstrip("\n")
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


def take_first(result):
    """Keep only the first result of a node/value set (--first)."""
    if isinstance(result, list):
        return result[:1]
    return result


def render(result, compact=False):
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
        return serialize_node(first, compact=compact)

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

    data = read_input(args.infile)

    root = build_document(data)

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

    if args.first:
        result = take_first(result)

    output = render(result, compact=args.compact)

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
