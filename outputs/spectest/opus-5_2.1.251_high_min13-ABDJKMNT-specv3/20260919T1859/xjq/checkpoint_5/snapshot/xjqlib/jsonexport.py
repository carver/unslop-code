"""Exporting matched elements as the JSON array that ``--json`` writes.

Each element becomes a one-key object pairing its tag with its immediate text,
and the objects are listed in the order the elements matched.
"""

import json

from lxml import etree

from .text import TextMode, extract_text, normalize

_INDENT = 2
_COMPACT_INDENT = 0


def is_exportable(nodes) -> bool:
    """Tell whether every node is an element, the only thing export is defined for.

    Comments and processing instructions are nodes of a document but carry no
    tag name, so a result holding one is left to the default node output.
    """
    return all(
        isinstance(node, etree._Element) and isinstance(node.tag, str) for node in nodes
    )


def export(elements, first: bool, compact: bool) -> str:
    """Render ``elements`` as the JSON array payload for stdout.

    ``first`` keeps the leading element, still inside an array; ``compact``
    lays the array out with zero indentation instead of two spaces.
    """
    exported = [_as_object(element) for element in (elements[:1] if first else elements)]
    indent = _COMPACT_INDENT if compact else _INDENT
    return json.dumps(exported, indent=indent) + "\n"


def _as_object(element: etree._Element) -> dict:
    """Pair an element's tag with its immediate text, normalized like any text."""
    return {element.tag: normalize(extract_text(element, TextMode.DIRECT))}
