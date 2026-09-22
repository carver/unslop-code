"""Turning the raw bytes read from stdin into a queryable document."""

from lxml import etree

from .errors import XjqError
from .jsondoc import build_document, load_container

# The XML parser (unlike lxml's HTML parser) keeps element names exactly as
# written, which is what makes element matching case-sensitive. The document's
# whitespace is kept as written, so that extracted text reads the way the
# source does; serialization re-indents from scratch instead.
_PARSER = etree.XMLParser()


def parse_document(data: bytes) -> etree._Element:
    """Return the root element of the document ``data`` holds.

    A JSON object or array is converted to XML; anything else, including a
    top-level JSON primitive, is parsed as XML. Raises :class:`XjqError` when
    the input is neither convertible JSON nor well-formed XML.
    """
    container = load_container(data)
    if container is None:
        return _parse_xml(data)
    return build_document(container)


def _parse_xml(data: bytes) -> etree._Element:
    """Parse ``data`` as XML, reporting anything empty or malformed."""
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as error:
        raise XjqError(f"could not parse xml input: {error}") from error
