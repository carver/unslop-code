"""The shape of a native (version 3) catalog: categories, fields and types."""

from .history import TRACKED_FIELDS

CATEGORIES = ("episodes", "streams", "clips")
VERSION = 3

#: Entry fields stored as plain values.
STATIC_FIELD_TYPES = {"id": str, "published": str, "width": int, "height": int}

#: Value types of the tracked fields that are fed by the source.
TRACKED_VALUE_TYPES = {
    "title": str,
    "description": str,
    "views": int,
    "likes": (int, type(None)),
    "preview": str,
}


def has_type(value, kind):
    """Type check that keeps JSON booleans out of integer fields."""
    return isinstance(value, kind) and not isinstance(value, bool)


def is_native(catalog):
    """Whether `catalog` matches the version 3 root and entry schema."""
    return (
        isinstance(catalog.get("source"), str)
        and all(isinstance(catalog.get(category), list) for category in CATEGORIES)
        and all(is_native_entry(entry) for category in CATEGORIES for entry in catalog[category])
    )


def is_native_entry(entry):
    """An entry needs its static fields plus six non-empty history objects."""
    return (
        isinstance(entry, dict)
        and all(has_type(entry.get(field), kind) for field, kind in STATIC_FIELD_TYPES.items())
        and all(isinstance(entry.get(field), dict) and entry[field] for field in TRACKED_FIELDS)
    )
