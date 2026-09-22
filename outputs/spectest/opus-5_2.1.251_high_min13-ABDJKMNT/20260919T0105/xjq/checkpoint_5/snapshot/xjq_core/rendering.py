"""Turning XPath results into the bytes the CLI prints."""

import math

from lxml import etree

from .extraction import normalize_space, string_value


def render(results, first=False, compact=False):
    """Render an XPath result as the text to print, or `None` to print nothing.

    Node results (elements, comments, processing instructions) are serialized
    XML, and only the first one is kept. Everything else — `text()` and
    attribute values, plus scalars from expressions such as `count(...)` — is
    whitespace normalised and laid out one result per line.

    `first` keeps only the leading result, which narrows the line-oriented
    output and leaves the already-single node output as it is. `compact`
    serializes nodes without the pretty-printer's added indentation, and has
    nothing to say about the line-oriented output.
    """
    values = results if isinstance(results, list) else [results]
    if not values:
        return None
    if first:
        values = values[:1]

    if etree.iselement(values[0]):
        serialized = etree.tostring(
            values[0], pretty_print=not compact, with_tail=False, encoding="unicode"
        )
        return serialized.strip()

    return "\n".join(_as_line(value) for value in values) or None


def _as_line(value):
    """Convert one result to a stripped, whitespace-collapsed line.

    A node can appear here when a query mixes text and element results, as a
    union of a `text()` path and an element path does; it contributes the text
    it stands for rather than a serialization.
    """
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        text = _format_number(value)
    else:
        text = string_value(value)
    return normalize_space(text)


def _format_number(value):
    """Format a number the way XPath 1.0's `string()` function does."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value.is_integer():
        return str(int(value))
    return repr(value)
