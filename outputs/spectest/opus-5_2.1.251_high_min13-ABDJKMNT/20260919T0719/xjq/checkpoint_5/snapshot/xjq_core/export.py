"""Exporting matched XML elements as JSON.

Each element becomes one object mapping its tag name to its immediate text, and
the export as a whole is the array of those objects. `--compact` keeps that
layout and only takes the indentation down to zero.
"""

import json

from .text import immediate_text

INDENT = 2


def export(elements, compact: bool = False, first: bool = False) -> str:
    """Render `elements` as the JSON array of `{tag: immediate text}` objects.

    `first` narrows the export to one element without unwrapping the array.
    """
    exported = elements[:1] if first else elements
    payload = [{element.tag: immediate_text(element)} for element in exported]
    return json.dumps(payload, indent=0 if compact else INDENT) + "\n"
