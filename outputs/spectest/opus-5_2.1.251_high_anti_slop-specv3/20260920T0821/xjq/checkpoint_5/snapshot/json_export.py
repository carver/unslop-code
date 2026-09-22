"""Exporting matched elements as JSON."""

import json

from lxml import etree

from query import Result
from text import TextMode, node_text, normalize

# The json.dumps indent each layout asks for. A compact export keeps the array
# and object structure but drops the leading whitespace of every line.
_INDENT = {False: 2, True: 0}


def exportable(result: Result) -> bool:
    """Whether ``result`` is the list of tagged elements an export is built from.

    Anything else — a scalar, an empty match, text, attributes, comments, or a
    union that matched elements alongside text — has no tag to export it under
    and is left to the default formatting.
    """
    return (
        isinstance(result, list)
        and bool(result)
        and all(
            isinstance(node, etree._Element) and isinstance(node.tag, str)
            for node in result
        )
    )


def export(
    elements: list[etree._Element], first: bool = False, compact: bool = False
) -> str:
    """Return ``elements`` as a JSON array of ``{tag name: text}`` objects.

    The text of an element is its immediate text, normalized like every other
    text result; the text of its child elements is left out. ``first`` exports
    only the leading element, still as an array.
    """
    if first:
        elements = elements[:1]
    exported = [
        {element.tag: normalize(node_text(element, TextMode.DIRECT))}
        for element in elements
    ]
    return json.dumps(exported, indent=_INDENT[compact], ensure_ascii=False)
