"""The JSON export `--json` produces from element results.

Each matched element becomes a one-key object mapping its tag name to its
immediate text, and those objects make up a JSON array.
"""

import json

from lxml import etree

from .extraction import immediate_text

#: Indent of the default layout; `--compact` asks for a zero-indent one.
_INDENT = 2


def export_json(values, compact=False):
    """Return the JSON text exporting the elements among `values`.

    Anything else a query matched alongside them — a text node from another
    union path, say — has no tag name to export and is left out.
    """
    exported = [
        {value.tag: immediate_text(value)}
        for value in values
        if etree.iselement(value)
    ]
    return json.dumps(exported, indent=0 if compact else _INDENT)
