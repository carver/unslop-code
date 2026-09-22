"""Reading and parsing the document that queries are evaluated against."""

import sys
from pathlib import Path

from lxml import etree

from errors import DocumentError
from json_xml import parse_json, to_xml


def read_source(path: str | None) -> bytes:
    """Return the bytes of the document at ``path``, or of stdin when None.

    A file is decoded as UTF-8, with a leading byte order mark allowed and
    dropped so that the JSON and XML parsers both see plain text.

    Raises:
        DocumentError: if the file cannot be read, or is not valid UTF-8.
    """
    if path is None:
        return sys.stdin.buffer.read()
    try:
        return Path(path).read_text(encoding="utf-8-sig").encode()
    except (OSError, UnicodeDecodeError) as exc:
        raise DocumentError(f"could not read input file {path!r}: {exc}") from exc


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` as JSON or as XML and return the root element to query.

    The format is detected from the input: a top-level JSON object or array is
    converted to the XML tree described in ``json_xml``, and anything else —
    including a top-level JSON primitive — is parsed as markup. Element and
    attribute names keep their original case, so markup written in mixed case
    (XHTML, SVG, custom vocabularies) stays queryable as authored. Blank text
    between elements is dropped so that matched nodes can be re-indented when
    they are printed.

    Raises:
        DocumentError: if the input is neither JSON nor well-formed XML.
        JsonError: if the input is JSON that XML cannot represent.
    """
    value = parse_json(data)
    if value is not None:
        return to_xml(value)
    parser = etree.XMLParser(remove_blank_text=True)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise DocumentError(f"could not parse xml input: {exc}") from exc
