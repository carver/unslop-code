"""Detection of JSON input and its conversion into a queryable element tree."""

import json
import re

from lxml import etree

#: Wrapper element of a converted document, and tag of every array entry.
ROOT_TAG = "root"
ITEM_TAG = "item"

#: ``type`` attribute values, keyed by the exact Python type ``json`` decodes
#: each JSON value into. Looking up ``type(value)`` rather than using
#: ``isinstance`` keeps booleans apart from the integers they subclass.
_TYPE_NAMES = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    dict: "dict",
    list: "list",
    type(None): "null",
}

# The XML 1.0 ``Name`` production, minus the colon: a key containing one would
# name a namespace prefix, and a converted document declares none.
_NAME_START = (
    "A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_CHAR = _NAME_START + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_CHAR}]*")


class JsonKeyError(Exception):
    """Raised when a JSON key cannot be used as an XML element name."""


def detect(data: bytes):
    """Return the JSON object or array held by ``data``, else ``None``.

    Detection is the decode itself: input that does not parse, or that parses
    to a top-level primitive, is not JSON input for this tool and belongs to
    the XML parser instead.
    """
    try:
        value = json.loads(data)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def build_document(value) -> etree._Element:
    """Return the ``<root>`` element for a decoded JSON object or array.

    ``<root>`` is the one element without a ``type``; everything below it is
    typed by the JSON value it came from.
    """
    root = etree.Element(ROOT_TAG)
    _fill(root, value)
    return root


def _fill(element, value) -> None:
    """Give ``element`` the children, or the text, that ``value`` maps to.

    Childless elements get empty text rather than none so that they serialize
    as ``<tag></tag>``; the contract rules out self-closing tags.
    """
    for tag, item in _entries(value):
        _fill(etree.SubElement(element, tag, type=_TYPE_NAMES[type(item)]), item)
    if len(element) == 0:
        element.text = _text(value)


def _entries(value):
    """Yield the ``(tag, value)`` children of a JSON object or array.

    Object keys are kept in their decoded order, and their case, so that the
    converted XML mirrors the source document.
    """
    if isinstance(value, dict):
        return [(_element_tag(key), item) for key, item in value.items()]
    if isinstance(value, list):
        return [(ITEM_TAG, item) for item in value]
    return []


def _element_tag(key: str) -> str:
    """Return ``key`` as an element name, rejecting names XML cannot spell."""
    if not _XML_NAME.fullmatch(key):
        raise JsonKeyError(f"{key!r} cannot be an xml element name")
    return key


def _text(value) -> str:
    """Return the element text of a JSON primitive; containers have none."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number_text(value)
    return value if isinstance(value, str) else ""


def _number_text(value) -> str:
    """Return the minimal string form of a JSON number.

    Integral floats drop their fraction (``1.0`` and ``1.50`` become ``1`` and
    ``1.5``); for the rest, Python's float repr is already the shortest string
    that round-trips, so ``0.00012`` keeps every digit.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
