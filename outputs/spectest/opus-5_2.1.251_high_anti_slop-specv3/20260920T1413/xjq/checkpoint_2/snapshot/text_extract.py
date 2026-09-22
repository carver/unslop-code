"""Text extraction from the elements matched by a query."""

import enum

from lxml import etree


class TextMode(enum.Enum):
    """Which text nodes of a matched element contribute to its text."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


def extract_text(result, mode: TextMode):
    """Return ``result`` with every matched element replaced by its text.

    Results that are not elements -- the strings of a ``text()`` or ``::text``
    query, attribute values, or the scalar of an XPath function -- already are
    text and are returned unchanged, which makes the text flags no-ops for
    queries that extract text themselves.
    """
    if not isinstance(result, list):
        return result
    return [_text_of(item, mode) if etree.iselement(item) else item for item in result]


def _text_of(element, mode: TextMode) -> str:
    """Join the text nodes of ``element`` selected by ``mode``."""
    if mode is TextMode.DESCENDANT:
        return "".join(element.itertext())
    return "".join(element.xpath("text()"))
