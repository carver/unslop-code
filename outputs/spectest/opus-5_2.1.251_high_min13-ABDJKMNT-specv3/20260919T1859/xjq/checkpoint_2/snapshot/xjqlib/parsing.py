"""Turning the raw bytes read from stdin into a queryable document."""

from lxml import etree

from .errors import XjqError

# The XML parser (unlike lxml's HTML parser) keeps element names exactly as
# written, which is what makes element matching case-sensitive. The document's
# whitespace is kept as written, so that extracted text reads the way the
# source does; serialization re-indents from scratch instead.
_PARSER = etree.XMLParser()


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` as XML and return its root element.

    Raises :class:`XjqError` when the input is empty or not well-formed.
    """
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as error:
        raise XjqError(f"could not parse xml input: {error}") from error
