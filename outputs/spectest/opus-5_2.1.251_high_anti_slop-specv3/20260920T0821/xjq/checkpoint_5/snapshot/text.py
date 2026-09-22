"""Text extraction from matched elements, and the normalization it feeds."""

import re
from enum import Enum

from lxml import etree

from query import Result


class TextMode(Enum):
    """Which text nodes of an element a text query collects."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


# The text nodes each mode reads, relative to a matched element.
TEXT_NODES = {TextMode.DIRECT: "text()", TextMode.DESCENDANT: ".//text()"}

_WHITESPACE_RUN = re.compile(r"\s+")


def node_text(element: etree._Element, mode: TextMode) -> str:
    """Return the text of ``element``, joining the text nodes ``mode`` reads."""
    return "".join(element.xpath(TEXT_NODES[mode]))


def extract(result: Result, mode: TextMode) -> Result:
    """Replace every element in ``result`` with its text, one string per element.

    Results that are not elements — attribute values, text nodes, scalars — are
    already text and are passed through untouched.
    """
    if not isinstance(result, list):
        return result
    return [
        node_text(node, mode) if isinstance(node, etree._Element) else node
        for node in result
    ]


def merge(texts: Result, first: bool = False) -> Result:
    """Concatenate extracted ``texts`` into the single string a union prints.

    The paths of a union pick out parts of one document, so their descendant
    text reads as one run rather than as a line per match. ``first`` keeps the
    leading match, letting a union print the text of just its first node.
    """
    if not isinstance(texts, list):
        return texts
    return ["".join(texts[:1] if first else texts)]


def normalize(text: str) -> str:
    """Strip ``text`` and collapse each run of internal whitespace to a space."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def extracts_text(query: str) -> bool:
    """Whether ``query`` already selects text, making the text flags a no-op.

    A union counts as soon as one of its paths selects text, because the flags
    cannot sensibly apply to only the rest of them.
    """
    return "text()" in query or "::text" in query
