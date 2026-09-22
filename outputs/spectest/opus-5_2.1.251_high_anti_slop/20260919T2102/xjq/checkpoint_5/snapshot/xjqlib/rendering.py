"""Formatting of XPath results into the text written to stdout."""

from dataclasses import dataclass

from lxml import etree

from .json_export import export
from .query import XPathResult
from .text import TextMode, extract_text, holds_text, joined_text, normalize


@dataclass(frozen=True)
class OutputOptions:
    """What the output flags ask for.

    Attributes:
        text: The text extraction the ``--text``/``--text-all`` flags ask for.
        json: Whether ``--json`` asks for the JSON export of the matched elements.
        union: Whether the query joins several paths with a top-level ``|``.
        first: Whether only the first result is wanted.
        compact: Whether the XML or JSON output drops its indentation.
    """

    text: TextMode
    json: bool
    union: bool
    first: bool
    compact: bool


def format_output(result: XPathResult, options: OutputOptions) -> str:
    """Render ``result`` as the output of a query, following the flag precedence.

    Text extraction wins over the JSON export, which in turn wins over the
    automatic formatting of ``render``. A result that is text already leaves
    every one of the output flags a no-op. The descendant text of a union query
    is concatenated into a single line, of which ``first`` keeps the share of
    the first matched node.
    """
    if holds_text(result):
        return render(result, first=options.first, compact=options.compact)
    matches = _limit(result, options.first)
    if options.text is TextMode.DESCENDANT and options.union:
        return joined_text(matches, TextMode.DESCENDANT)
    if options.text is TextMode.NONE and options.json and matches:
        return export(matches, compact=options.compact)
    return render(extract_text(result, options.text), first=options.first, compact=options.compact)


def render(result: XPathResult, *, first: bool, compact: bool) -> str:
    """Render an XPath result as the output of a query.

    Element results are serialized XML, one element after the other; every other
    kind of result is whitespace-normalized, one match per line, leaving out the
    matches that hold no text at all. ``first`` keeps only the first element or
    line of the output and ``compact`` drops the indentation of the XML.
    """
    if not isinstance(result, list):
        return normalize(_scalar_to_text(result))
    elements = [item for item in result if isinstance(item, etree._Element)]
    if elements:
        return "\n".join(serialize(element, compact) for element in _limit(elements, first))
    lines = [normalize(str(item)) for item in result]
    return "\n".join(_limit([line for line in lines if line], first))


def serialize(element: etree._Element, compact: bool) -> str:
    """Serialize a single element as XML, indented unless ``compact`` is asked for."""
    return etree.tostring(element, pretty_print=not compact, encoding="unicode").rstrip("\n")


def _limit(items: list, first: bool) -> list:
    """Cut ``items`` down to its first entry when only the first result is wanted."""
    return items[:1] if first else items


def _scalar_to_text(value: str | float | bool) -> str:
    """Convert an XPath boolean/number/string result to its XPath 1.0 lexical form."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
