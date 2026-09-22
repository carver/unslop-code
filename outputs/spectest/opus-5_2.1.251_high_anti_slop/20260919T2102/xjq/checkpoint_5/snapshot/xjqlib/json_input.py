"""Conversion of JSON input into the element tree the queries run against."""

import json
import re

from lxml import etree

from .errors import XjqError

JsonValue = dict | list | str | int | float | bool | None

ROOT_TAG = "root"
ITEM_TAG = "item"

# The XML 1.0 Name production, minus the colon: a colon asks lxml for a namespace
# prefix, and a JSON document has no way to declare one.
_NAME_START = (
    "A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf\ufdf0-\ufffd"
)
_NAME_REST = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_ELEMENT_NAME = re.compile(f"[{_NAME_START}][{_NAME_REST}]*\\Z")

# json.loads only ever yields these seven types, so an exact type lookup is enough
# and keeps ``bool`` from being mistaken for the ``int`` it subclasses.
_TYPE_NAMES = {
    dict: "dict",
    list: "list",
    str: "str",
    bool: "bool",
    int: "int",
    float: "float",
    type(None): "null",
}


def parse_json(data: bytes) -> etree._Element | None:
    """Convert ``data`` into a ``<root>`` element tree if it is a JSON document.

    Returns ``None`` when ``data`` is not JSON at all or is a top-level JSON
    primitive; the caller falls back to XML/HTML for both. Object keys become
    child elements in their original order and array entries become ``<item>``
    children. Every element below ``<root>`` carries a ``type`` attribute naming
    the JSON type it came from.

    Raises:
        XjqError: a JSON key cannot be used as an XML element name.
    """
    try:
        value = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(value, (dict, list)):
        return None
    root = etree.Element(ROOT_TAG)
    _fill(root, value)
    return root


def _fill(element: etree._Element, value: JsonValue) -> None:
    """Give ``element`` the children ``value`` contributes, or its text."""
    if isinstance(value, dict):
        for key, entry in value.items():
            _append(element, _element_name(key), entry)
    elif isinstance(value, list):
        for entry in value:
            _append(element, ITEM_TAG, entry)
    else:
        element.text = _primitive_text(value)


def _append(parent: etree._Element, tag: str, value: JsonValue) -> None:
    """Add a typed child element for one JSON value and fill it in turn."""
    _fill(etree.SubElement(parent, tag, {"type": _TYPE_NAMES[type(value)]}), value)


def _element_name(key: str) -> str:
    """Return ``key`` unchanged, rejecting keys that are not XML element names."""
    if _ELEMENT_NAME.match(key) is None:
        raise XjqError(f"error: invalid json key {key!r}: not a valid xml element name")
    return key


def _primitive_text(value: str | int | float | bool | None) -> str | None:
    """Render a JSON primitive as element text.

    Booleans keep their JSON spelling and ``null`` contributes no text. Numbers
    use their shortest round-tripping form, with integral floats losing the
    trailing ``.0`` so that ``1.0`` and ``1`` both read as ``1``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if value is None:
        return None
    return str(value)
