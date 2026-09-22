"""Reading the XML document that queries are evaluated against."""

from lxml import etree

from .errors import XmlParseError


def parse_document(source: bytes) -> etree._Element:
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
