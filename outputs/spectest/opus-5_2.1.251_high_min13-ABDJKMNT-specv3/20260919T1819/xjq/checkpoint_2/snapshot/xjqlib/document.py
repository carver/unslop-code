"""Turning the bytes read from stdin into a queryable element tree."""

from lxml import etree


class DocumentError(Exception):
    """Raised when stdin does not hold a usable XML document."""


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` and return the root element.

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
