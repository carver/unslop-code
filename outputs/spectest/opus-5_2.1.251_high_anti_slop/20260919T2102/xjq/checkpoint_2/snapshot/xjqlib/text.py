"""Extraction of text nodes from the elements a query matched."""

from enum import Enum

from lxml import etree

from .query import XPathResult


class TextMode(Enum):
    """How much text a matched element contributes.

    The value of a text-producing mode is the XPath step that collects the text
    nodes of an element.
    """

    NONE = ""
    DIRECT = "text()"
    DESCENDANT = "descendant-or-self::text()"


def extract_text(result: XPathResult, mode: TextMode) -> XPathResult:
    """Replace every element in ``result`` by the text nodes selected by ``mode``.

    Results that are already text -- those of an XPath ``text()`` step, of a
    ``::text`` pseudo-element or of a string-valued expression -- are returned
    unchanged, which makes the text flags no-op modifiers for such queries.
    """
    if mode is TextMode.NONE or not isinstance(result, list):
        return result
    texts: list = []
    for item in result:
        if isinstance(item, etree._Element):
            texts.extend(item.xpath(mode.value))
        else:
            texts.append(item)
    return texts
