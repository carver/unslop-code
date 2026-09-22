"""Text extraction from the elements a query matched."""

import enum

from lxml import etree


class TextMode(enum.Enum):
    """How the elements of a query result are turned into text."""

    NONE = "none"
    DIRECT = "direct"
    DESCENDANT = "descendant"
    NODES = "nodes"


def mode_from_flags(text: bool, text_all: bool) -> TextMode:
    """Return the mode requested by ``--text``/``--text-all``.

    ``--text-all`` wins when both are given.
    """
    if text_all:
        return TextMode.DESCENDANT
    return TextMode.DIRECT if text else TextMode.NONE


def _direct(element: etree._Element) -> list:
    """The element's immediate text children, concatenated into one result."""
    return ["".join(element.xpath("text()"))]


def _descendant(element: etree._Element) -> list:
    """All text below the element, concatenated into one result."""
    return ["".join(element.itertext())]


def _nodes(element: etree._Element) -> list:
    """Every descendant text node of the element, as a result of its own."""
    return element.xpath(".//text()")


_EXTRACTORS = {
    TextMode.DIRECT: _direct,
    TextMode.DESCENDANT: _descendant,
    TextMode.NODES: _nodes,
}


def extract(result, mode: TextMode):
    """Replace the elements of ``result`` with their text.

    Items that are not elements -- attribute and text results, and the scalars
    returned by functions such as ``count()`` -- have no text to extract and
    are passed through, which is what makes the text flags no-ops for queries
    that already select text.
    """
    if mode is TextMode.NONE or not isinstance(result, list):
        return result
    extractor = _EXTRACTORS[mode]
    extracted = []
    for item in result:
        extracted.extend(extractor(item) if etree.iselement(item) else [item])
    return extracted
