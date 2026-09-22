"""Recognizing a JSON document on stdin and converting it to XML.

A JSON object or array becomes a ``<root>`` element whose descendants mirror the
document: keys become tags, array entries become ``<item>`` elements, and every
element but ``<root>`` records the JSON type it came from in ``type``.
"""

import json

from lxml import etree

from .errors import XjqError
from .names import is_xml_name

ROOT_TAG = "root"
ITEM_TAG = "item"

# The seven type names the contract allows, keyed by the exact Python type
# ``json`` produces. Exact types matter: ``bool`` is a subclass of ``int``.
_TYPE_NAMES = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    dict: "dict",
    list: "list",
    type(None): "null",
}


def load_container(data: bytes):
    """Return the JSON object or array in ``data``, or ``None`` for other input.

    A top-level primitive is not JSON input for this mode, and neither is text
    that does not parse; both give ``None`` so the caller can fall back to XML.
    """
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, (dict, list)) else None


def build_document(value) -> etree._Element:
    """Convert a JSON object or array into the ``<root>`` element that holds it.

    Raises :class:`XjqError` when a key cannot be used as an element name.
    """
    root = etree.Element(ROOT_TAG)
    _fill(root, value)
    return root


def _fill(element: etree._Element, value) -> None:
    """Give ``element`` the children of a container, or the text of a primitive."""
    if not isinstance(value, (dict, list)):
        element.text = _primitive_text(value)
        return
    for tag, entry in _child_entries(value):
        _fill(etree.SubElement(element, tag, type=_TYPE_NAMES[type(entry)]), entry)
    if len(element) == 0:
        # Empty text is what makes an empty container serialize as a pair of
        # tags rather than as a self-closing one.
        element.text = ""


def _child_entries(value):
    """Yield the ``(tag, value)`` pairs a container contributes, in source order."""
    if isinstance(value, dict):
        return [(_checked_key(key), entry) for key, entry in value.items()]
    return [(ITEM_TAG, entry) for entry in value]


def _checked_key(key: str) -> str:
    """Return ``key`` unchanged, rejecting one that is not an XML element name."""
    if not is_xml_name(key):
        raise XjqError(f"invalid json key {key!r}: not a valid xml element name")
    return key


def _primitive_text(value) -> str:
    """Render a JSON primitive as element text; null renders as no text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number_text(value)
    return str(value)


def _number_text(number: float) -> str:
    """Spell a float minimally: ``1.0`` as ``1``, ``1.50`` as ``1.5``.

    ``repr`` gives the shortest spelling that still round-trips, except for
    whole numbers, which it writes with a trailing ``.0``.
    """
    if number.is_integer():
        return str(int(number))
    return repr(number)
