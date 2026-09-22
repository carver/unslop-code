"""Turning the bytes read from stdin into a queryable element tree."""

from lxml import etree

from xjqlib.json_input import build_document, detect


class DocumentError(Exception):
    """Raised when stdin does not hold a usable XML document."""


def parse_document(data: bytes) -> etree._Element:
    """Return the root element for stdin, choosing the format by detection.

    A JSON object or array is converted; everything else -- including a
    top-level JSON primitive -- is parsed as XML.
    """
    value = detect(data)
    if value is None:
        return _parse_xml(data)
    return build_document(value)


def _parse_xml(data: bytes) -> etree._Element:
    """Parse ``data`` as XML and return its root element.

    Element names are matched case-sensitively, which rules out lxml's HTML
    parser (it lowercases tag names); HTML-shaped input is therefore read with
    the XML parser as well. Source indentation is dropped so that serialized
    results can be re-indented from the tree instead of inheriting the layout
    of the input.
    """
    if not data.strip():
        raise DocumentError("input is empty")
    try:
        return etree.fromstring(data, etree.XMLParser(remove_blank_text=True))
    except etree.XMLSyntaxError as exc:
        raise DocumentError(str(exc)) from exc
