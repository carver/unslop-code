"""Recognizing an XPath union so that the text flags can span it.

`|` joins location paths into one node set. The flags behave differently over
a union than over a single path, so the CLI has to tell the two apart before
the query runs -- which means reading the expression rather than its result.
"""


def is_union(expression: str) -> bool:
    """Report whether `expression` joins sub-paths with a top-level `|`."""
    return len(split(expression)) > 1


def split(expression: str) -> list[str]:
    """Split `expression` into the sub-paths its top-level `|` separates.

    A `|` inside a predicate, an argument list or a string literal belongs to
    that construct, so only one at nesting depth zero and outside quotes is the
    union operator.
    """
    sub_paths = [""]
    depth = 0
    quote = ""
    for char in expression:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "|" and depth == 0:
            sub_paths.append("")
            continue
        sub_paths[-1] += char
    return [sub_path.strip() for sub_path in sub_paths]
