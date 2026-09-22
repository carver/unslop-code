"""Export of the matched elements as a JSON document."""

import json

from lxml import etree

from .text import TextMode, joined_text

_INDENT = 2


def export(elements: list[etree._Element], *, compact: bool) -> str:
    """Render ``elements`` as a JSON array of ``{tag name: text}`` objects.

    Only the immediate text of an element is exported; the text its child
    elements hold is left out. The array is laid out with a two space indent
    unless ``compact`` asks for the zero-indent layout.
    """
    exported = [{element.tag: joined_text([element], TextMode.DIRECT)} for element in elements]
    return json.dumps(exported, indent=0 if compact else _INDENT, ensure_ascii=False)
