"""Extracting the text of matched elements."""

import enum

from lxml import etree


class TextMode(enum.Enum):
    """Which text nodes of an element make up its extracted text."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


def requested_mode(text: bool, text_all: bool) -> TextMode | None:
    """Return the extraction mode asked for on the command line.

    ``--text-all`` wins when both flags are given; without either, node results
    keep their XML serialization.
    """
    if text_all:
        return TextMode.DESCENDANT
    return TextMode.DIRECT if text else None


def extract_text(element: etree._Element, mode: TextMode) -> str:
    """Return the text of ``element`` as one string.

    Direct extraction concatenates the element's own child text nodes;
    descendant extraction takes the XPath string-value, which is every text
    node in the subtree.
    """
    if mode is TextMode.DESCENDANT:
        return element.xpath("string(.)")
    return "".join(element.xpath("text()"))
