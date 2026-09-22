"""Translation of CSS selectors into the XPath the query stage evaluates.

Beyond standard CSS this understands one custom pseudo-element, `::text`, in
its two spellings: `div::text` selects the direct text nodes of each match and
`div ::text` selects every descendant text node. Both are stripped out here and
re-expressed as a trailing XPath step, so the rest of the tool only ever sees
an XPath expression.
"""

import re

import cssselect
from cssselect import GenericTranslator, SelectorError

from .errors import CssSelectorError, MixedTextModeError

#: `::text` closing one selector of a (possibly comma-separated) query. The
#: captured gap is what distinguishes the two modes: `a::text` has none,
#: `a ::text` has the descendant combinator's whitespace.
_TEXT_PSEUDO = re.compile(r"(?P<gap>\s*)::text(?=\s*(?:,|$))")

#: XPath step that realises each `::text` mode against the matched elements.
_TEXT_STEPS = {"direct": "/text()", "descendant": "//text()"}

_TRANSLATOR = GenericTranslator()


def css_to_xpath(selector):
    """Return the XPath 1.0 expression equivalent to CSS `selector`.

    Raises `MixedTextModeError` when the comma-separated parts do not agree on
    a single `::text` mode, and `CssSelectorError` when the remaining selector
    is not valid CSS.
    """
    tagged = _TEXT_PSEUDO.findall(selector)
    modes = {"descendant" if gap else "direct" for gap in tagged}
    parts = _parse(_TEXT_PSEUDO.sub("", selector))

    if len(modes) > 1 or (tagged and len(tagged) != len(parts)):
        raise MixedTextModeError()

    union = " | ".join(_translate(part) for part in parts)
    if not modes:
        return union
    return f"({union}){_TEXT_STEPS[modes.pop()]}"


def _parse(source):
    """Split `source` into its individual comma-separated CSS selectors."""
    try:
        return cssselect.parse(source)
    except SelectorError as exc:
        raise CssSelectorError(exc) from exc


def _translate(parsed):
    """Convert one parsed selector into an XPath location path.

    Pseudo-elements are translated rather than ignored, so anything other than
    the `::text` already removed above is reported as an unsupported selector.
    """
    try:
        return _TRANSLATOR.selector_to_xpath(parsed, translate_pseudo_elements=True)
    except SelectorError as exc:
        raise CssSelectorError(exc) from exc
