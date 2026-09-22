"""Auto-detection of the format of the document read from standard input."""

from json_input import parse_json
from xml_input import parse_xml


def parse_document(data: bytes):
    """Return the root element of ``data``, whatever format it is in.

    A JSON object or array is converted into an XML tree; anything else,
    including a top-level JSON primitive, is parsed as XML or HTML.

    Raises:
        JsonKeyError: if a JSON object key is not a valid XML element name.
        XmlParseError: if non-JSON input is not a well-formed document.
    """
    document = parse_json(data)
    if document is None:
        return parse_xml(data)
    return document
