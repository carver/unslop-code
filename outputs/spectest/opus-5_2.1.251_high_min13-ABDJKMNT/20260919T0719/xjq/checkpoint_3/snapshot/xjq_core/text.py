"""Extracting text from the elements that a query matched."""

from enum import Enum

from lxml import etree


class TextMode(Enum):
    """Which text nodes to take from a matched element.

    Each member's value is the XPath step that selects those nodes relative to
    the element: the direct children only, or the whole subtree.
    """

    DIRECT = "text()"
    DESCENDANT = "descendant-or-self::text()"


def extract_text(result, mode: TextMode | None):
    """Replace matched elements with their text nodes, one result per node.

    A query that already yields text, attributes or a scalar has no elements to
    extract from, so `mode` is ignored and the result passes through unchanged.
    That is what makes `--text` and `--text-all` no-op modifiers for a query
    such as `//title/text()` or `p::text`.
    """
    if mode is None or not _is_element_set(result):
        return result
    return [node for element in result for node in element.xpath(mode.value)]


def _is_element_set(result) -> bool:
    """Report whether `result` is a non-empty node set made only of elements."""
    return (
        isinstance(result, list)
        and bool(result)
        and all(isinstance(node, etree._Element) for node in result)
    )
