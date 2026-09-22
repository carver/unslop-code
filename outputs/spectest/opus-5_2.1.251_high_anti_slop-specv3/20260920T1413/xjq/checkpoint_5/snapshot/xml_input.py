"""Parsing of the XML/HTML input document."""

from lxml import etree, html

from errors import XmlParseError

# Element names keep their case in XML, so the XML parser is always tried
# first; the HTML fallback is reserved for documents that announce themselves
# as HTML, where tag names are lower case by definition.
_HTML_MARKERS = (b"<!doctype html", b"<html")

# Entity resolution is disabled because the input document is untrusted.
_XML_PARSER = etree.XMLParser(resolve_entities=False)


def parse_xml(data: bytes):
    """Return the root element of ``data``, preserving element name case.

    Raises:
        XmlParseError: if ``data`` is empty or is not a well-formed document.
    """
    if not data.strip():
        raise XmlParseError("xml parse error: input is empty")
    try:
        return etree.fromstring(data, _XML_PARSER)
    except etree.XMLSyntaxError as exc:
        if _looks_like_html(data):
            return html.document_fromstring(data)
        raise XmlParseError(f"xml parse error: {exc}") from exc


def _looks_like_html(data: bytes) -> bool:
    """Report whether ``data`` starts out as an HTML document."""
    head = data[:512].lower()
    return any(marker in head for marker in _HTML_MARKERS)
