"""Detecting a JSON document on stdin and converting it into an XML tree.

The converted tree is what queries run against, so the conversion is the whole
contract: a `<root>` wrapper, one element per object key or array entry, and a
`type` attribute on everything below the root naming the JSON kind it came
from.
"""

import json
import re

from lxml import etree

from .errors import JsonKeyError

ROOT_TAG = "root"
ITEM_TAG = "item"

# The XML 1.0 Name production minus the colon: a colon introduces a namespace
# prefix, and a JSON key brings no declaration that could bind one.
_NAME_START = (
    "A-Z_a-z\xc0-\xd6\xd8-\xf6\xf8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
_NAME_REST = _NAME_START + "\\-.0-9\xb7\u0300-\u036f\u203f-\u2040"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_REST}]*\\Z")

# JSON kinds, keyed by exact type so that `True` is a bool rather than an int.
_TYPE_NAMES = {
    str: "str",
    bool: "bool",
    int: "int",
    float: "float",
    dict: "dict",
    list: "list",
    type(None): "null",
}


def detect(source: bytes):
    """Return the JSON document `source` holds, or `None` if it holds none.

    Only objects and arrays count as documents: a top-level primitive decodes
    fine but has no keys or entries to convert, so it is left to the XML
    parser along with everything that fails to decode at all.
    """
    try:
        document = json.loads(source)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, (dict, list)) else None


def build_tree(document) -> etree._Element:
    """Convert a decoded JSON object or array into its `<root>` element.

    The root is the one element without a `type`, since it stands for the
    document rather than for a value inside it.
    """
    root = etree.Element(ROOT_TAG)
    _fill(root, document)
    return root


def _fill(element, value) -> None:
    """Populate `element` from `value`: children for containers, text for the rest."""
    if isinstance(value, dict):
        for key, member in value.items():
            _append(element, _element_name(key), member)
    elif isinstance(value, list):
        for entry in value:
            _append(element, ITEM_TAG, entry)
    else:
        element.text = _primitive_text(value)


def _append(parent, tag: str, value) -> None:
    """Add the element `value` converts to, named `tag`, to `parent`."""
    element = etree.SubElement(parent, tag)
    element.set("type", _TYPE_NAMES[type(value)])
    _fill(element, value)


def _element_name(key: str) -> str:
    """Return `key` as an element tag name, rejecting keys that cannot be one."""
    if _XML_NAME.match(key) is None:
        raise JsonKeyError(f"invalid json key {key!r}: not a valid xml element name")
    return key


def _primitive_text(value) -> str | None:
    """Render a JSON primitive as element text, `None` meaning no text at all."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number_text(value)
    return str(value)


def _number_text(value: float) -> str:
    """Render a float in minimal form, dropping a fractional part of zero."""
    return str(int(value)) if value.is_integer() else repr(value)
