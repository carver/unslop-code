"""Reading and parsing the XML document that queries are evaluated against."""

from lxml import etree

from errors import DocumentError


def parse_document(data: bytes) -> etree._Element:
    """Parse ``data`` as XML and return its root element.

    Element and attribute names keep their original case, so markup written in
    mixed case (XHTML, SVG, custom vocabularies) stays queryable as authored.
    Blank text between elements is dropped so that matched nodes can be
    re-indented when they are printed.

    Raises:
        DocumentError: if the input is empty or not well-formed XML.
    """
    parser = etree.XMLParser(remove_blank_text=True)
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise DocumentError(f"could not parse xml input: {exc}") from exc
