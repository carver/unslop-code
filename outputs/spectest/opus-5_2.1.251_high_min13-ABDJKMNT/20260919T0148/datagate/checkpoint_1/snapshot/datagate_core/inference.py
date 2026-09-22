"""Value typing: the rule that decides which CSV cells become JSON numbers."""

import re

# Numbers are recognised by grammar rather than by trying int()/float(), so that
# JSON-illegal floats (nan, inf) and Python-only spellings (1_000) stay text, and
# so that anything with other characters -- times, dates, currency -- stays text.
INTEGER = re.compile(r"[+-]?[0-9]+\Z")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def coerce_value(text):
    """Return `text` as an int or float when it is a plain number, else unchanged."""
    literal = text.strip()
    if INTEGER.match(literal):
        return int(literal)
    if DECIMAL.match(literal):
        return float(literal)
    return text
