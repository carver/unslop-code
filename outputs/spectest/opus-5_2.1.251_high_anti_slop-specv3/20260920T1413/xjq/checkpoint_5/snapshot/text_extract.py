"""Text extraction from the elements matched by a query, and its normalization."""

import enum
import re

_WHITESPACE_RUN = re.compile(r"\s+")


class TextMode(enum.Enum):
    """Which text nodes of a matched element contribute to its text."""

    DIRECT = "direct"
    DESCENDANT = "descendant"


def element_text(element, mode: TextMode) -> str:
    """Join the text nodes of ``element`` selected by ``mode``.

    ``DIRECT`` keeps the text that belongs to the element itself and
    ``DESCENDANT`` adds the text of every child element as well.
    """
    if mode is TextMode.DESCENDANT:
        return "".join(element.itertext())
    return "".join(element.xpath("text()"))


def extract_text(elements, mode: TextMode) -> list:
    """Return the text of each of ``elements``, one string per element."""
    return [element_text(element, mode) for element in elements]


def join_text(elements) -> str:
    """Return the descendant text of every element of ``elements`` as one string.

    This is how the text of a union query is reported: the matches of all of
    its sub-paths read as a single run of text rather than one line each.
    """
    return normalize_text(
        "".join(element_text(element, TextMode.DESCENDANT) for element in elements)
    )


def normalize_text(text: str) -> str:
    """Strip ``text`` and collapse each run of internal whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
