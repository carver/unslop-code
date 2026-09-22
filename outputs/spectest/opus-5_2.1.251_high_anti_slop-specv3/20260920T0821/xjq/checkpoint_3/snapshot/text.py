"""Text extraction from matched elements."""

from enum import Enum

from lxml import etree

from query import Result


class TextMode(Enum):
    """Which text nodes of an element a text query collects."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


# The text nodes each mode reads, relative to a matched element.
TEXT_NODES = {TextMode.DIRECT: "text()", TextMode.DESCENDANT: ".//text()"}


def extract(result: Result, mode: TextMode) -> Result:
    """Replace every element in ``result`` with its text, one string per element.

    Results that are not elements — attribute values, text nodes, scalars — are
    already text and are passed through untouched.
    """
    if not isinstance(result, list):
        return result
    return [
        "".join(node.xpath(TEXT_NODES[mode]))
        if isinstance(node, etree._Element)
        else node
        for node in result
    ]


def extracts_text(query: str) -> bool:
    """Whether ``query`` already selects text, making the text flags a no-op."""
    return "text()" in query or "::text" in query
