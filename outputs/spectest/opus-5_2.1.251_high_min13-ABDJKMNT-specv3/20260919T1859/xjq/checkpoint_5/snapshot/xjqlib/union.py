"""Recognizing an XPath expression that unions several sub-paths."""

_QUOTES = "'\""


def has_union(expression: str) -> bool:
    """Tell whether ``expression`` uses the XPath ``|`` union operator.

    Only a bar outside string literals counts, so ``//t[contains(., '|')]``
    selects elements the ordinary way rather than as a union.
    """
    quote = None
    for character in expression:
        if quote is not None:
            quote = None if character == quote else quote
        elif character in _QUOTES:
            quote = character
        elif character == "|":
            return True
    return False
