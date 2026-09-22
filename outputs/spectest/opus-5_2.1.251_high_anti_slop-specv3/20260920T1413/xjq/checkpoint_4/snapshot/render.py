"""Formatting of XPath results into the text written to stdout."""

import copy
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")
_INDENT = "  "


def render(result, first: bool = False, compact: bool = False) -> str:
    """Return the stdout text for an XPath ``result``, without a trailing newline.

    A node set that starts with an element is rendered as the XML of that first
    element; any other node set is rendered as one whitespace-normalized line
    per result, or as a single line when ``first`` is set. ``compact`` drops the
    pretty-printing of XML output, leaving the document's own layout.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if first:
        result = result[:1]
    if not result:
        return ""
    if etree.iselement(result[0]):
        return _serialize(result[0], compact)
    return "\n".join(_normalize(item) for item in result)


def _render_scalar(value) -> str:
    """Render the boolean, number or string produced by an XPath function."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return number_text(value)
    return _normalize(value)


def number_text(value: float) -> str:
    """Return the shortest string that denotes the number ``value``."""
    return str(int(value)) if value.is_integer() else repr(value)


def _serialize(node, compact: bool) -> str:
    """Return the XML of ``node`` and its descendants, pretty-printed unless ``compact``."""
    if compact:
        return etree.tostring(node, with_tail=False, encoding="unicode").strip()
    indented = copy.deepcopy(node)
    etree.indent(indented, space=_INDENT)
    xml = etree.tostring(indented, pretty_print=True, with_tail=False, encoding="unicode")
    return xml.strip()


def _normalize(text: str) -> str:
    """Strip ``text`` and collapse each run of internal whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
