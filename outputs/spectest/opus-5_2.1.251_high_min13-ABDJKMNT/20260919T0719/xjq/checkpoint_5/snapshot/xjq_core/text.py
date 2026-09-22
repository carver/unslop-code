"""Extracting text from the elements that a query matched."""

from enum import Enum

from .nodes import is_element_set
from .render import normalize


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
    such as `//title/text()` or `p::text`, and for a union in which one
    sub-path extracts text.
    """
    if mode is None or not is_element_set(result):
        return result
    return [node for element in result for node in element.xpath(mode.value)]


def concatenate_descendant_text(elements, first: bool = False) -> str:
    """Join the descendant text of every element into one normalized string.

    This is what `--text-all` means across a union: the matches form a single
    run of text rather than one line each. `first` narrows the run to the first
    matched node, which still contributes all of its own descendant text.
    """
    contributors = elements[:1] if first else elements
    runs = [normalize("".join(node.xpath(TextMode.DESCENDANT.value))) for node in contributors]
    return " ".join(run for run in runs if run)


def immediate_text(element) -> str:
    """Return the element's own text, leaving its children's text out.

    Both text before and text after a child element are the element's own, so
    `<p>Beta <sub>deep</sub> tail</p>` reads as `Beta tail`.
    """
    return normalize("".join(element.xpath(TextMode.DIRECT.value)))
