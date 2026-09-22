"""Turning the raw stdin byte stream into a queryable document tree.

The stream carries either JSON or XML, told apart by trying to decode it as a
JSON object or array; anything else is XML's.
"""

from lxml import etree

from .errors import XmlInputError
from .json_input import json_to_xml


def parse_document(data):
    """Parse `data` (bytes) as XML and return the root element.

    A top-level JSON object or array is converted to XML first (see
    `json_input`); everything else, top-level JSON primitives included, is
    parsed as XML.

    Bytes rather than text are parsed so that any encoding declaration in the
    document is honoured. The XML parser is strict and case-sensitive: element
    and attribute names keep the case they were written with, and input that is
    not well-formed raises `XmlInputError` rather than being silently recovered.
    """
    if not data.strip():
        raise XmlInputError("input is empty")

    converted = json_to_xml(data)
    if converted is not None:
        return converted

    try:
        return etree.fromstring(data, parser=etree.XMLParser())
    except etree.XMLSyntaxError as exc:
        raise XmlInputError(exc) from exc
