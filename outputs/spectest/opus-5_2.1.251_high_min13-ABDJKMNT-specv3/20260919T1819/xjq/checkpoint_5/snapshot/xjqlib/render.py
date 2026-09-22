"""Rendering of XPath results into the text written to stdout."""

from lxml import etree

from xjqlib.json_export import export
from xjqlib.text import descendant_text, normalize


def render(result, first=False, compact=False, json_export=False) -> str:
    """Return the stdout text for ``result``, without a trailing newline.

    A result of nothing but elements is serialized: as a JSON export of every
    match under ``json_export``, cut to one entry by ``first``, and otherwise
    as the XML of its first match. Every other result is written as text --
    normalized, one per line, cut to its first entry under ``first`` -- which
    is where a text or attribute result lands, and a union of mixed types with
    it. Anything that is not a node list is a scalar from a function such as
    ``count()``, which is one result already.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if not result:
        return ""
    if all(map(etree.iselement, result)):
        if json_export:
            return export(result[:1] if first else result, compact)
        return _render_element(result[0], compact)
    items = result[:1] if first else result
    return "\n".join(normalize(_as_text(item)) for item in items)


def _as_text(item) -> str:
    """The text a result item contributes to text output."""
    return descendant_text(item) if etree.iselement(item) else str(item)


def _render_element(element, compact: bool) -> str:
    """Serialize an element, pretty-printed unless compact output was asked for.

    Compact output adds no indentation of its own, and the source indentation
    was already dropped at parse time, so the element serializes on one line.
    """
    return etree.tostring(
        element, pretty_print=not compact, with_tail=False, encoding="unicode"
    ).rstrip("\n")


def _render_scalar(value) -> str:
    """Format a non node-set result the way XPath 1.0 ``string()`` would."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize(str(value))
