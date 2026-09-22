"""Turning the raw stdin byte stream into a queryable document tree."""

from lxml import etree

from .errors import XmlInputError


def parse_document(data):
    """Parse `data` (bytes) as XML and return the root element.

    Bytes rather than text are parsed so that any encoding declaration in the
    document is honoured. The parser is strict and case-sensitive: element and
    attribute names keep the case they were written with, and input that is not
    well-formed raises `XmlInputError` rather than being silently recovered.
    """
    if not data.strip():
        raise XmlInputError("input is empty")

    try:
        return etree.fromstring(data, parser=etree.XMLParser())
    except etree.XMLSyntaxError as exc:
        raise XmlInputError(exc) from exc
