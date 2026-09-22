"""Detection of JSON input and its conversion into an XML document.

A converted document is wrapped in a `<root>` element: the keys of a top-level
object become its children, while the entries of a top-level array become
`<item>` children. Every converted element but `<root>` records the JSON type
it came from in a `type` attribute, so that queries can tell an `int` from the
`str` that happens to hold the same digits.
"""

import json
import re

from lxml import etree

# The XML 1.0 Name production, minus the colon: lxml reserves colons for
# namespace prefixes and refuses to build an element whose tag contains one.
_NAME_START = (
    "A-Za-z_\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf\ufdf0-\ufffd"
)
_NAME_CHAR = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_CHAR}]*")

_TYPE_NAMES = {
    type(None): "null",
    bool: "bool",
    int: "int",
    float: "float",
    str: "str",
    dict: "dict",
    list: "list",
}


class JsonInputError(Exception):
    """The input is JSON, but holds a key that no XML element can be named."""


def parse_document(data):
    """Return the `<root>` element for the JSON in `data` (bytes).

    None is returned when `data` is not a JSON object or array, which is the
    caller's signal to parse it as XML instead. Top-level primitives are
    rejected this way too: there is no document to build out of them.
    """
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, (dict, list)):
        return None
    root = etree.Element("root")
    _fill(root, value)
    return root


def _fill(element, value):
    """Populate `element` with the children or the text representing `value`."""
    if isinstance(value, dict):
        for key, entry in value.items():
            _append(element, _checked_tag(key), entry)
    elif isinstance(value, list):
        for entry in value:
            _append(element, "item", entry)
    else:
        element.text = _text(value)


def _append(parent, tag, value):
    """Append a `tag` child holding `value` and its JSON type to `parent`."""
    _fill(etree.SubElement(parent, tag, type=_TYPE_NAMES[type(value)]), value)


def _checked_tag(key):
    """Return `key` as an element tag, rejecting the ones XML cannot express."""
    if not _XML_NAME.fullmatch(key):
        raise JsonInputError(f"{key!r} is not a valid xml element name")
    return key


def _text(value):
    """Render a JSON primitive as element text, null becoming no text at all."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number_text(value)
    return str(value)


def _number_text(value):
    """Return the shortest form of a JSON float: `1.0` and `1.50` become `1` and `1.5`."""
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text
