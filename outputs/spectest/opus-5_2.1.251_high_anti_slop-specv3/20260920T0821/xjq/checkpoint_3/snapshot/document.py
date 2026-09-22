"""Reading and parsing the document that queries are evaluated against."""

from lxml import etree

from errors import DocumentError
from json_xml import parse_json, to_xml


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
