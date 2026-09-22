"""Building blocks for the `xjq` XPath/CSS querying CLI."""

from .css import css_to_xpath
from .errors import (
    CssSelectorError,
    MixedTextModeError,
    XjqError,
    XmlInputError,
    XPathQueryError,
)
from .extraction import DESCENDANT, DIRECT, extract_text
from .parsing import parse_document
from .query import evaluate
from .rendering import render

__all__ = [
    "CssSelectorError",
    "MixedTextModeError",
    "XjqError",
    "XmlInputError",
    "XPathQueryError",
    "DESCENDANT",
    "DIRECT",
    "css_to_xpath",
    "extract_text",
    "parse_document",
    "evaluate",
    "render",
]
