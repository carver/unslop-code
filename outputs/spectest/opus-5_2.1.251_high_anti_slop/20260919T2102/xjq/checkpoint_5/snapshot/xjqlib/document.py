"""Turning raw input bytes into an element tree."""

from lxml import etree

from .errors import XjqError
from .json_input import parse_json

# The XML parser is used even for HTML-ish input because element names must stay
# case-sensitive; lxml's HTML parser lowercases every tag and attribute name.
# Blank-only text nodes are dropped so that serialized nodes can be re-indented.
_PARSER = etree.XMLParser(remove_blank_text=True, resolve_entities=False)


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` and return the root element to query.

    A JSON object or array is converted to XML; anything else, including a
    top-level JSON primitive, is parsed as XML/HTML.

    Raises:
        XjqError: the input is empty, holds an unusable JSON key, or is not
            well-formed XML.
    """
    if not data.strip():
        raise XjqError("error: could not parse xml input: no input given")
    converted = parse_json(data)
    if converted is not None:
        return converted
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise XjqError(f"error: could not parse xml input: {exc}") from exc
