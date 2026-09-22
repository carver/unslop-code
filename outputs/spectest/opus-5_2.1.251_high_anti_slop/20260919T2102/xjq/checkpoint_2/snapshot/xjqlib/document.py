"""Turning raw input bytes into an element tree."""

from lxml import etree

from .errors import XjqError

# The XML parser is used even for HTML-ish input because element names must stay
# case-sensitive; lxml's HTML parser lowercases every tag and attribute name.
# Blank-only text nodes are dropped so that serialized nodes can be re-indented.
_PARSER = etree.XMLParser(remove_blank_text=True, resolve_entities=False)


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` as XML and return its root element.

    Raises:
        XjqError: the input is empty or not well-formed.
    """
    if not data.strip():
        raise XjqError("error: could not parse xml input: no input given")
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise XjqError(f"error: could not parse xml input: {exc}") from exc
