"""Export of the elements a query matched as a JSON array."""

import json

import textnodes


def export(elements, compact=False):
    """Return the JSON text for `elements`, one object per matched element.

    Every object holds a single entry mapping the element's tag name to the
    text immediately below it, whitespace-normalized and with the text of
    child elements left out. The array is indented by two spaces unless
    `compact` asks for the zero-indent layout, which keeps one value per line
    without any leading whitespace.
    """
    payload = [
        {element.tag: textnodes.joined([element], textnodes.DIRECT)}
        for element in elements
    ]
    return json.dumps(payload, indent=0 if compact else 2, ensure_ascii=False) + "\n"
