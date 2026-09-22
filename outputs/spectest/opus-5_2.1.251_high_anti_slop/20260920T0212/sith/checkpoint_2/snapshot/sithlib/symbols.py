"""How completion candidates are typed, described and ordered."""

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
STATEMENT = "statement"
PARAM = "param"
KEYWORD = "keyword"

_PUBLIC, _PRIVATE, _DUNDER, _KEYWORD = range(4)


def sort_key(name, kind):
    """Public names, then private, then dunders, then keywords; alphabetical within."""
    return (_group(name, kind), name.lower())


def as_completion(name, kind, description, prefix_length):
    """Render a candidate as the JSON object the CLI emits."""
    return {
        "name": name,
        "complete": name[prefix_length:],
        "type": kind,
        "description": description,
    }


def _group(name, kind):
    if kind == KEYWORD:
        return _KEYWORD
    if name.startswith("__") and name.endswith("__"):
        return _DUNDER
    return _PRIVATE if name.startswith("_") else _PUBLIC
