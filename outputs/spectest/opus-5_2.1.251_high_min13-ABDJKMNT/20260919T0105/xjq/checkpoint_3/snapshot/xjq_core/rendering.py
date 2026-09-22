"""Turning XPath results into the bytes the CLI prints."""

import math
import re

from lxml import etree

_WHITESPACE = re.compile(r"\s+")


def render(results):
    """Render an XPath result as the text to print, or `None` to print nothing.

    Node results (elements, comments, processing instructions) are pretty-printed
    XML, and only the first one is kept. Everything else — `text()` and attribute
    values, plus scalars from expressions such as `count(...)` — is whitespace
    normalised and laid out one result per line.
    """
    values = results if isinstance(results, list) else [results]
    if not values:
        return None

    if etree.iselement(values[0]):
        serialized = etree.tostring(
            values[0], pretty_print=True, with_tail=False, encoding="unicode"
        )
        return serialized.strip()

    return "\n".join(_as_line(value) for value in values) or None


def _as_line(value):
    """Convert one non-node result to a stripped, whitespace-collapsed line."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        text = _format_number(value)
    else:
        text = str(value)
    return _WHITESPACE.sub(" ", text).strip()


def _format_number(value):
    """Format a number the way XPath 1.0's `string()` function does."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value.is_integer():
        return str(int(value))
    return repr(value)
