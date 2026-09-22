"""Export of the elements matched by a query as a JSON document."""

import json

from text_extract import TextMode, element_text, normalize_text

_INDENT = 2
_COMPACT_INDENT = 0


def export_json(elements, compact: bool = False) -> str:
    """Return ``elements`` as a JSON array of ``{tag: text}`` objects.

    Only the text that belongs to an element itself is exported; the text held
    by its child elements is left out. The array is indented by two spaces,
    or laid out without any leading whitespace when ``compact`` is set.
    """
    exported = [
        {element.tag: normalize_text(element_text(element, TextMode.DIRECT))}
        for element in elements
    ]
    indent = _COMPACT_INDENT if compact else _INDENT
    return json.dumps(exported, indent=indent, ensure_ascii=False)
