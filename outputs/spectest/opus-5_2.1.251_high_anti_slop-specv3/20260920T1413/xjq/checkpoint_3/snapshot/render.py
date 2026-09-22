"""Formatting of XPath results into the text written to stdout."""

import copy
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")
_INDENT = "  "


def render(result) -> str:
    """Return the stdout text for an XPath ``result``, without a trailing newline.

    A node set that starts with an element is rendered as the pretty-printed
    XML of that first element; any other node set is rendered as one
    whitespace-normalized line per result.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if not result:
        return ""
    if etree.iselement(result[0]):
        return _serialize(result[0])
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


def _serialize(node) -> str:
    """Pretty-print ``node`` and its descendants as XML."""
    indented = copy.deepcopy(node)
    etree.indent(indented, space=_INDENT)
    xml = etree.tostring(indented, pretty_print=True, with_tail=False, encoding="unicode")
    return xml.strip()


def _normalize(text: str) -> str:
    """Strip ``text`` and collapse each run of internal whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
