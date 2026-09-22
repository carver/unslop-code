"""Conversion of a JSON input document into an XML tree.

A JSON object or array is turned into a ``<root>`` element that the XPath and
CSS queries can then walk: object keys become element names, array entries
become ``<item>`` elements, and every element but ``<root>`` records the JSON
type of its value in a ``type`` attribute.
"""

import json
import re

from lxml import etree

from errors import JsonKeyError
from render import number_text

_TYPE_NAMES = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    dict: "dict",
    list: "list",
    type(None): "null",
}

# The XML 1.0 Name production, minus the colon, which lxml reserves for
# namespace prefixes.
_NAME_START = (
    "A-Za-z_\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf\ufdf0-\ufffd"
)
_NAME_CHAR = _NAME_START + "0-9.\\-\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_CHAR}]*\\Z")


def parse_json(data: bytes):
    """Return the ``<root>`` element for ``data``, or ``None`` if it is not JSON.

    Only JSON objects and arrays count as JSON input; a top-level primitive is
    reported as not-JSON so that the caller can fall back to XML parsing.

    Raises:
        JsonKeyError: if an object key is not a valid XML element name.
    """
    try:
        value = json.loads(data)
    except ValueError:
        return None
    if not isinstance(value, (dict, list)):
        return None
    root = etree.Element("root")
    _fill(root, value)
    return root


def _fill(element, value) -> None:
    """Give ``element`` the text or the children that represent ``value``."""
    if isinstance(value, dict):
        _append_children(element, value.items())
    elif isinstance(value, list):
        _append_children(element, (("item", item) for item in value))
    else:
        element.text = _primitive_text(value)


def _append_children(element, tagged_values) -> None:
    """Append one typed child per ``(tag, value)`` pair, in the order given."""
    for tag, value in tagged_values:
        child = etree.SubElement(element, _element_name(tag), type=_TYPE_NAMES[type(value)])
        _fill(child, value)
    if len(element) == 0:
        # An empty container still has to serialize as <tag></tag>; an empty
        # string text -- unlike None -- keeps lxml from self-closing the tag.
        element.text = ""


def _element_name(key: str) -> str:
    """Return ``key`` as an element name.

    Raises:
        JsonKeyError: if ``key`` cannot be used as an XML element name.
    """
    if not _XML_NAME.match(key):
        raise JsonKeyError(f"json error: invalid key {key!r}: not a valid XML element name")
    return key


def _primitive_text(value) -> str:
    """Return the element text of a JSON string, number, boolean or null."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return number_text(value)
    return str(value)
