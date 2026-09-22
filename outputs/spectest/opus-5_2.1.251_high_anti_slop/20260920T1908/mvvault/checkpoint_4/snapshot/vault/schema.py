"""The shape shared by every catalog: its version, categories and entry fields."""

CATEGORIES = ("episodes", "streams", "clips")
VERSION = 3

STATIC_FIELDS = {
    "id": str,
    "published": str,
    "width": int,
    "height": int,
}

TRACKED_FIELDS = {
    "title": str,
    "description": str,
    "views": int,
    "likes": (int, type(None)),
    "preview": str,
}

REMOVED_FIELD = "removed"


def matches_type(value, expected) -> bool:
    """No entry field accepts a boolean, which ``isinstance`` would read as an int."""
    return not isinstance(value, bool) and isinstance(value, expected)
