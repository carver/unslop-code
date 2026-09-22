"""Building blocks for the `xjq` XPath/CSS querying CLI."""

from .css import css_to_xpath
from .errors import (
    CssSelectorError,
    JsonKeyError,
    MixedTextModeError,
    XjqError,
    XmlInputError,
    XPathQueryError,
)
from .extraction import DESCENDANT, DIRECT, extract_text
from .json_input import json_to_xml
from .parsing import parse_document
from .query import evaluate
from .rendering import render

__all__ = [
    "CssSelectorError",
    "JsonKeyError",
    "MixedTextModeError",
    "XjqError",
    "XmlInputError",
    "XPathQueryError",
    "DESCENDANT",
    "DIRECT",
    "css_to_xpath",
    "extract_text",
    "json_to_xml",
    "parse_document",
    "evaluate",
    "render",
]
