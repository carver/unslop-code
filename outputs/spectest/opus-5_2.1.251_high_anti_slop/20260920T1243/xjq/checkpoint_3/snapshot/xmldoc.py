"""Parsing of XML input and evaluation of XPath 1.0 queries against it.

Input is parsed with lxml's XML parser rather than its HTML parser: the XML
parser keeps element names case-sensitive, while the HTML parser lower-cases
them and silently repairs documents that should be reported as malformed.
"""

from lxml import etree


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
