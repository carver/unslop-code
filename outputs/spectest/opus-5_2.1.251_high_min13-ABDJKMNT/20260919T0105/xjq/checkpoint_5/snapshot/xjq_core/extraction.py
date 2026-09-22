"""Text extraction requested by `--text` and `--text-all`.

The flags rewrite element results into the text nodes those elements hold,
which is the same shape a `text()` or `::text` query returns directly. Results
that are already text — attribute values, text nodes, scalars — have nothing to
extract and pass through, which is exactly what makes the flags no-ops for
queries that extract text themselves.

The helpers below also serve the two places that need an element's text as one
string rather than as separate nodes: the JSON export and the single string a
union query under `--text-all` produces.
"""

import re

from lxml import etree

DIRECT = "direct"
DESCENDANT = "descendant"

#: Relative XPath selecting the text nodes each mode is interested in.
_TEXT_PATHS = {DIRECT: "text()", DESCENDANT: ".//text()"}

_WHITESPACE = re.compile(r"\s+")


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


def normalize_space(text):
    """Strip `text` and collapse its internal whitespace runs to single spaces."""
    return _WHITESPACE.sub(" ", text).strip()


def string_value(value):
    """Return the text `value` stands for.

    For an element that is its descendant text, run together as the document
    wrote it; for a text node, attribute value or scalar it is the value
    itself.
    """
    if etree.iselement(value):
        return "".join(value.xpath(_TEXT_PATHS[DESCENDANT]))
    return str(value)


def immediate_text(element):
    """Return `element`'s own text, normalized, excluding its children's."""
    return normalize_space("".join(element.xpath(_TEXT_PATHS[DIRECT])))


def joined_text(values):
    """Concatenate the text of every value in `values` into one line.

    A union query under `--text-all` presents all of its matches as a single
    normalized string. Separate matches are spaced apart so that the last word
    of one and the first of the next do not run together.
    """
    return normalize_space(" ".join(string_value(value) for value in values))
