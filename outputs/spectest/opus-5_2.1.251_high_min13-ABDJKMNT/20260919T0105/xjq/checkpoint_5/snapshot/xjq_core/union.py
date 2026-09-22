"""The top-level `|` structure of an XPath expression.

Evaluating a union is lxml's job. What the CLI needs to know beforehand is
whether the query *is* a union, because `--text-all` then presents all the
matches as one string, and whether any of its paths already ends in a text
step, which turns the text flags into no-op modifiers.
"""

import re

#: A path ending in `text()`, optionally followed by predicates. Anchoring at
#: the end is what separates a text-extracting path from one that merely tests
#: text in a predicate, such as `//a[text()='x']`.
_TEXT_STEP = re.compile(r"text\s*\(\s*\)\s*(?:\[[^\]]*\])*\s*$")


def split_union(expression):
    """Split `expression` at the `|` operators joining its top-level paths.

    A `|` inside quotes, parentheses or a predicate belongs to a
    sub-expression rather than to the query, and is left where it is.
    """
    paths, start, depth, quote = [], 0, 0, ""
    for index, char in enumerate(expression):
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "|" and depth == 0:
            paths.append(expression[start:index])
            start = index + 1
    paths.append(expression[start:])
    return paths


def is_union(expression):
    """True when `expression` joins two or more paths with `|`."""
    return len(split_union(expression)) > 1


def extracts_text(expression):
    """True when a path of `expression` already returns text nodes."""
    return any(_TEXT_STEP.search(path) for path in split_union(expression))
