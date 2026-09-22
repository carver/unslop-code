"""Detecting JSON input and converting it to the XML tree queries run against.

A JSON document becomes a ``<root>`` element whose children mirror the
document's structure: object keys become tag names, array entries become
``<item>`` elements, and primitives become element text. Every element below
``<root>`` records where it came from in a ``type`` attribute, so queries can
tell ``"1"`` from ``1`` and an empty element from a null.
"""

import json
import re

from lxml import etree

from errors import JsonError

# The JSON values a document is built from.
Json = dict | list | str | int | float | bool | None

ROOT_TAG = "root"
ITEM_TAG = "item"

# The ``type`` attribute written for each kind of JSON value.
_TYPE_NAMES = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    dict: "dict",
    list: "list",
    type(None): "null",
}

# The characters XML 1.0 allows in an element name, minus ``:``, which would
# read as a namespace prefix that a JSON document has no way to declare.
_NAME_START = (
    "A-Z_a-zÀ-ÖØ-öø-˿Ͱ-ͽͿ-῿"
    "‌-‍⁰-↏Ⰰ-⿯、-퟿豈-﷏"
    "ﷰ-�\U00010000-\U000effff"
)
_NAME_REST = _NAME_START + "0-9·̀-ͯ‿-⁀.-"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_REST}]*")


def parse_json(data: bytes) -> dict | list | None:
    """Return the JSON object or array in ``data``, or None if it holds neither.

    Only objects and arrays count as JSON input; a top-level primitive — a bare
    string, number, boolean or null — reads as None so that the caller falls
    back to parsing ``data`` as markup.
    """
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def to_xml(value: dict | list) -> etree._Element:
    """Return ``value`` as a ``<root>`` element ready to be queried.

    ``<root>`` itself carries no ``type``; the object's keys, or the array's
    entries, hang directly beneath it in their original order.

    Raises:
        JsonError: if a key anywhere in ``value`` is not a valid XML element
            name.
    """
    root = etree.Element(ROOT_TAG)
    _fill(root, value)
    return root


def _fill(element: etree._Element, value: Json) -> None:
    """Give ``element`` the children, or the text, that ``value`` maps to."""
    if isinstance(value, dict):
        for key, item in value.items():
            _fill(_child(element, _element_name(key), item), item)
    elif isinstance(value, list):
        for item in value:
            _fill(_child(element, ITEM_TAG, item), item)
    else:
        element.text = _text(value)


def _child(parent: etree._Element, tag: str, value: Json) -> etree._Element:
    """Append the element ``value`` becomes, tagged with its JSON type."""
    return etree.SubElement(parent, tag, type=_TYPE_NAMES[type(value)])


def _element_name(key: str) -> str:
    """Return ``key`` as an element name, rejecting keys XML cannot spell."""
    if not _XML_NAME.fullmatch(key):
        raise JsonError(f"invalid json key {key!r}: not a valid xml element name")
    return key


def _text(value: str | int | float | bool | None) -> str:
    """Render a JSON primitive as element text.

    Booleans are spelled ``true`` and ``false``, null is the empty string, and
    numbers take their shortest form: ``1.0`` prints as ``1`` and ``1.50`` as
    ``1.5``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
