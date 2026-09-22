"""Text extraction requested by `--text` and `--text-all`.

The flags rewrite element results into the text nodes those elements hold,
which is the same shape a `text()` or `::text` query returns directly. Results
that are already text — attribute values, text nodes, scalars — have nothing to
extract and pass through, which is exactly what makes the flags no-ops for
queries that extract text themselves.
"""

from lxml import etree

DIRECT = "direct"
DESCENDANT = "descendant"

#: Relative XPath selecting the text nodes each mode is interested in.
_TEXT_PATHS = {DIRECT: "text()", DESCENDANT: ".//text()"}


def extract_text(results, mode):
    """Replace every element in `results` with its text nodes.

    `mode` is `DIRECT`, `DESCENDANT`, or `None` to leave `results` alone.
    Non-list results, such as the number an XPath `count()` returns, are also
    returned unchanged.
    """
    if mode is None or not isinstance(results, list):
        return results

    path = _TEXT_PATHS[mode]
    extracted = []
    for value in results:
        extracted.extend(value.xpath(path) if etree.iselement(value) else [value])
    return extracted
