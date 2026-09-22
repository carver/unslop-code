"""The version 3 catalog: its categories, entry ordering, and root schema."""

#: The three content categories a catalog stores, in their canonical order.
CATEGORIES = ("episodes", "streams", "clips")

#: Catalog format this tool writes. Older formats are migrated on load.
VERSION = 3


def new_catalog(source_url):
    """The exact layout a freshly initialized vault starts with."""
    return {"version": VERSION, "source": source_url, "episodes": [], "streams": [], "clips": []}


def sort_entries(entries):
    """Order entries newest `published` first, ties broken by smaller `id`.

    Both keys are compared as text: normalized `published` values are
    fixed-width, so lexicographic order is chronological order. Sorting by the
    tie-breaker first and relying on a stable sort keeps the two directions
    independent.
    """
    by_id = sorted(entries, key=lambda entry: entry["id"])
    return sorted(by_id, key=lambda entry: entry["published"], reverse=True)


def validate_catalog(data):
    """Raise ValueError if `data` is not a usable v3 catalog.

    The version is already established by the loader, and entry contents are
    maintained exclusively by this tool, so only the root schema is checked.
    """
    if not isinstance(data.get("source"), str):
        raise ValueError("catalog has no usable source URL")
    for category in CATEGORIES:
        if not isinstance(data.get(category), list):
            raise ValueError(f"catalog field {category!r} is missing or not an array")
