"""Building blocks for the `xjq` XPath/CSS querying CLI."""

from .css import css_to_xpath
from .errors import (
    CssSelectorError,
    FileInputError,
    JsonKeyError,
    MixedTextModeError,
    XjqError,
    XmlInputError,
    XPathQueryError,
)
from .extraction import DESCENDANT, DIRECT, extract_text
from .json_export import export_json
from .json_input import json_to_xml
from .output import OutputOptions, format_results
from .parsing import parse_document
from .query import evaluate
from .rendering import render
from .source import read_document
from .union import extracts_text, is_union

__all__ = [
    "CssSelectorError",
    "FileInputError",
    "JsonKeyError",
    "MixedTextModeError",
    "XjqError",
    "XmlInputError",
    "XPathQueryError",
    "DESCENDANT",
    "DIRECT",
    "OutputOptions",
    "css_to_xpath",
    "export_json",
    "extract_text",
    "extracts_text",
    "format_results",
    "is_union",
    "json_to_xml",
    "parse_document",
    "read_document",
    "evaluate",
    "render",
]
