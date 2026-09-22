"""Extracting and normalizing the text of matched elements."""

import enum
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


class TextMode(enum.Enum):
    """Which text nodes of an element make up its extracted text."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


def requested_mode(text: bool, text_all: bool) -> TextMode | None:
    """Return the extraction mode asked for on the command line.

    ``--text-all`` wins when both flags are given; without either, node results
    keep their XML serialization or, under ``--json``, their export.
    """
    if text_all:
        return TextMode.DESCENDANT
    return TextMode.DIRECT if text else None


def extract_text(element: etree._Element, mode: TextMode) -> str:
    """Return the text of ``element`` as one string.

    Direct extraction concatenates the element's own child text nodes, which
    includes the text written after a child element's closing tag; descendant
    extraction takes the XPath string-value, which is every text node in the
    subtree.
    """
    if mode is TextMode.DESCENDANT:
        return element.xpath("string(.)")
    return "".join(element.xpath("text()"))


def normalize(text: str) -> str:
    """Strip the ends of ``text`` and squeeze internal whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text.strip())
