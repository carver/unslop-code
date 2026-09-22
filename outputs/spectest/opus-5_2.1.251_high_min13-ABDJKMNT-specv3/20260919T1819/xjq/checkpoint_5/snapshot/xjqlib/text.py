"""Text extraction from the elements a query matched."""

import enum
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


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


def normalize(text: str) -> str:
    """Strip ``text`` and collapse its internal whitespace runs to spaces."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def direct_text(element: etree._Element) -> str:
    """The text nodes that are immediate children of ``element``, joined."""
    return "".join(element.xpath("text()"))


def descendant_text(element: etree._Element) -> str:
    """Every text node below ``element``, joined: its XPath string value."""
    return "".join(element.itertext())


_EXTRACTORS = {
    TextMode.DIRECT: lambda element: [direct_text(element)],
    TextMode.DESCENDANT: lambda element: [descendant_text(element)],
    #: One result per text node rather than one per element.
    TextMode.NODES: lambda element: element.xpath(".//text()"),
}


def extract(result, mode: TextMode, first: bool = False, union: bool = False):
    """Replace the elements of ``result`` with their text.

    A result holding anything but elements -- the text nodes and attributes a
    query selects itself, or the scalar a function such as ``count()`` returns
    -- is text already, so the flags have nothing to extract and are left as
    no-op query modifiers. That covers a union whose sub-paths extract text.

    A union asked for descendant text answers with one string rather than one
    per match, built from the first match alone when ``first`` is set.
    """
    if mode is TextMode.NONE or not _holds_only_elements(result):
        return result
    if union and mode is TextMode.DESCENDANT:
        return [_union_text(result[:1] if first else result)]
    extractor = _EXTRACTORS[mode]
    return [text for element in result for text in extractor(element)]


def _union_text(elements) -> str:
    """The descendant text of every element as one normalized string.

    The matches are spaced apart before normalizing so that the last word of
    one cannot run into the first word of the next.
    """
    return normalize(" ".join(descendant_text(element) for element in elements))


def _holds_only_elements(result) -> bool:
    """Whether ``result`` is a node list of nothing but elements."""
    return isinstance(result, list) and all(map(etree.iselement, result))
