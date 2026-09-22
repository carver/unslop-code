"""Parsing of XML input and evaluation of XPath 1.0 queries against it.

Input is parsed with lxml's XML parser rather than its HTML parser: the XML
parser keeps element names case-sensitive, while the HTML parser lower-cases
them and silently repairs documents that should be reported as malformed.
"""

import re

from lxml import etree

# A `|` anywhere else than inside a string literal is the union operator:
# XPath 1.0 gives the character no other meaning.
_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


class XmlInputError(Exception):
    """The input is empty or is not a well-formed XML document."""


class XPathQueryError(Exception):
    """The query is not a usable XPath 1.0 expression."""


def parse_document(data):
    """Parse `data` (bytes) and return the root element of the document.

    Whitespace-only text between elements is dropped so that serialized output
    can be re-indented cleanly.
    """
    parser = etree.XMLParser(remove_blank_text=True)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise XmlInputError(exc) from exc


def evaluate(root, query):
    """Evaluate `query` against `root` and return the raw XPath 1.0 result.

    The result is a list of nodes and/or strings for a node set, or a bool,
    float or string for the other three XPath 1.0 types.
    """
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        raise XPathQueryError(exc) from exc


def is_union(query):
    """Return whether `query` joins several paths with the XPath union operator."""
    return "|" in _STRING_LITERAL.sub("", query)


def is_element_set(result):
    """Return whether an XPath result is a node set holding elements only.

    A result holding strings is one the query itself reduced to text, with an
    `@attribute` or a `text()` step; it is left to be rendered as such.
    """
    return isinstance(result, list) and all(
        etree.iselement(value) for value in result
    )
