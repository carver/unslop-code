"""Conversion of JSON stdin into the XML tree the query stages already speak.

A JSON object or array is rewritten as a `<root>` element: object keys become
tag names, array entries become `<item>` elements, and every element below the
root records the JSON kind of its value in a `type` attribute. Primitives land
in the element's text, so `//price/text()` reads a JSON number the same way it
reads an XML one.
"""

import json
import re

from lxml import etree

from .errors import JsonKeyError

#: The XML 1.0 `Name` production without the colon, which lxml reserves for
#: namespace prefixes. Keys outside it cannot name an element.
_NAME_START = (
    "A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF"
    "\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF"
    "\uFDF0-\uFFFD"
)
_NAME_REST = _NAME_START + "\\-.0-9\u00B7\u0300-\u036F\u203F-\u2040"
_XML_NAME = re.compile(f"[{_NAME_START}][{_NAME_REST}]*")

#: JSON kind names, keyed by the exact Python type `json.loads` produces. The
#: lookup is by identity rather than `isinstance` so that `True`, a Python
#: `int` subclass, is still reported as a boolean.
_TYPE_NAMES = {
    type(None): "null",
    bool: "bool",
    int: "int",
    float: "float",
    str: "str",
    dict: "dict",
    list: "list",
}


def json_to_xml(data):
    """Return the `<root>` element for `data`, or `None` if it is not JSON.

    `None` means "let the XML parser have it": `data` is either not JSON at
    all, or a top-level primitive, which this mode deliberately does not accept
    as JSON input.

    Raises `JsonKeyError` for an object key that cannot name an XML element.
    """
    try:
        document = json.loads(data)
    except ValueError:
        return None

    if not isinstance(document, (dict, list)):
        return None

    root = etree.Element("root")
    _populate(root, document)
    return root


def _build(tag, value):
    """Build the element named `tag` holding the JSON `value`."""
    element = etree.Element(tag, type=_TYPE_NAMES[type(value)])
    _populate(element, value)
    return element


def _populate(element, value):
    """Fill `element` from `value`: children for containers, text otherwise."""
    if isinstance(value, dict):
        element.extend(_build(_tag_for(key), item) for key, item in value.items())
    elif isinstance(value, list):
        element.extend(_build("item", item) for item in value)
    else:
        element.text = _primitive_text(value)


def _tag_for(key):
    """Return `key` as an element tag, rejecting keys XML cannot name."""
    if not _XML_NAME.fullmatch(key):
        raise JsonKeyError(key)
    return key


def _primitive_text(value):
    """Render a JSON primitive as element text; null contributes no text.

    Numbers use their shortest round-tripping form with an integral float
    written without its fractional part, so `1`, `1.0` and `1.50` become `1`,
    `1` and `1.5`.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
