"""Export of matched elements as a JSON array of tag name and text."""

import json

from xjqlib.text import direct_text, normalize

#: Indentation of the exported array. ``--compact`` keeps the layout but lays
#: every line out flush left.
_INDENT = 2
_COMPACT_INDENT = 0


def export(elements, compact: bool = False) -> str:
    """Return the JSON array text for ``elements``, without a trailing newline.

    Every element becomes a one-key object of its tag name and its immediate
    text: the text nodes the element owns itself, normalized like any other
    text this tool writes, and without the text of the elements below it.
    """
    entries = [{element.tag: normalize(direct_text(element))} for element in elements]
    return json.dumps(entries, indent=_COMPACT_INDENT if compact else _INDENT)
