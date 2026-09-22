#!/usr/bin/env python3
"""xjq - query XML/HTML from stdin with XPath 1.0.

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


PROG = "xjq"


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query XML/HTML read from stdin using an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        default=None,
        help="accepted but ignored; input is always read from stdin",
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
    result = evaluate(root, args.query)
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
