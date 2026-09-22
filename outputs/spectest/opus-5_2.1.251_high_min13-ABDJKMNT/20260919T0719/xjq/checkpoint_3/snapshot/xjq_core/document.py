"""Reading the document that queries are evaluated against.

Stdin holds either a JSON object/array or an XML document; which one it is
gets decided by the input itself rather than by a flag.
"""

from lxml import etree

from .errors import XmlParseError
from .json_input import build_tree, detect


def parse_document(source: bytes) -> etree._Element:
    """Parse `source` and return the document element to query.

    JSON is tried first and converted to XML when it is found; anything else,
    including a top-level JSON primitive, falls through to the XML parser.
    """
    document = detect(source)
    if document is None:
        return parse_xml(source)
    return build_tree(document)


def parse_xml(source: bytes) -> etree._Element:
    """Parse `source` as XML and return its document element.

    Bytes are handed to lxml unchanged so that an XML declaration can select
    the encoding. The XML parser is used rather than the HTML one because it
    matches element and attribute names case-sensitively and rejects malformed
    or empty input instead of silently recovering from it.
    """
    try:
        return etree.fromstring(source, etree.XMLParser())
    except etree.XMLSyntaxError as exc:
        raise XmlParseError(f"failed to parse xml input: {exc}") from exc
