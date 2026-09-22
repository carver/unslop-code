"""Extraction of text nodes from the elements a query matched."""

import re
from enum import Enum

from lxml import etree

from .query import XPathResult

_WHITESPACE_RUN = re.compile(r"\s+")


class TextMode(Enum):
    """How much text a matched element contributes.

    The value of a text-producing mode is the XPath step that collects the text
    nodes of an element.
    """

    NONE = ""
    DIRECT = "text()"
    DESCENDANT = "descendant-or-self::text()"


def holds_text(result: XPathResult) -> bool:
    """Tell whether ``result`` is already text instead of a set of elements.

    That is the case for the result of an XPath ``text()`` or attribute step, of
    a ``::text`` pseudo-element and of a string-valued expression -- also when
    only one sub-path of a union extracts text -- which is what makes the text
    and JSON flags no-op query modifiers for such queries.
    """
    return not isinstance(result, list) or not all(
        isinstance(item, etree._Element) for item in result
    )


def extract_text(elements: list[etree._Element], mode: TextMode) -> list:
    """Replace every element in ``elements`` by the text nodes ``mode`` selects.

    The elements are handed back untouched for ``TextMode.NONE``, the mode of a
    query that was asked for no text extraction at all.
    """
    if mode is TextMode.NONE:
        return elements
    return [text for element in elements for text in element.xpath(mode.value)]


def joined_text(elements: list[etree._Element], mode: TextMode) -> str:
    """Concatenate the text ``mode`` selects across ``elements`` into one string.

    The text nodes are concatenated before being normalized, so that whitespace
    around a child element still separates the words it sits between.
    """
    return normalize("".join(extract_text(elements, mode)))


def normalize(text: str) -> str:
    """Strip the text and collapse internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
