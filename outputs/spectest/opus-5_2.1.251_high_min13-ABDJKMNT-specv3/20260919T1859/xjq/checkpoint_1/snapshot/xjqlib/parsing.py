"""Turning the raw bytes read from stdin into a queryable document."""

from lxml import etree

from .errors import XjqError

# The XML parser (unlike lxml's HTML parser) keeps element names exactly as
# written, which is what makes element matching case-sensitive. Whitespace-only
# text nodes are dropped so that serialized results can be re-indented from
# scratch instead of inheriting the source document's layout.
_PARSER = etree.XMLParser(remove_blank_text=True)


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` as XML and return its root element.

    Raises :class:`XjqError` when the input is empty or not well-formed.
    """
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as error:
        raise XjqError(f"could not parse xml input: {error}") from error
