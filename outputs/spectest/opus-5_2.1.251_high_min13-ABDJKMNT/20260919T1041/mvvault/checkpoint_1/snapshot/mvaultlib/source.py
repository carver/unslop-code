"""Fetching and validating media-platform source metadata."""

import requests

from .catalog import CATEGORIES
from .errors import SourceError
from .timestamps import normalize_datetime

REQUEST_TIMEOUT = 30

#: The nine fields every source entry must carry, with their accepted types.
ENTRY_FIELD_TYPES = {
    "id": str,
    "published": str,
    "width": int,
    "height": int,
    "title": str,
    "description": str,
    "views": int,
    "likes": (int, type(None)),
    "preview": str,
}


def fetch(url):
    """GET `url` and return `{category: [validated entry, ...]}`.

    Every failure - transport, status, JSON syntax, or schema - is reported as
    a source metadata fetch failure so the caller can leave the vault alone.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SourceError(f"could not fetch source metadata from {url}: {exc}") from None

    if not isinstance(payload, dict):
        raise SourceError(f"source metadata from {url} is not a JSON object")
    return {category: _read_category(payload, category, url) for category in CATEGORIES}


def _read_category(payload, category, url):
    entries = payload.get(category)
    if not isinstance(entries, list):
        raise SourceError(f"source metadata from {url} has no '{category}' array")
    return [_read_entry(raw, category, url) for raw in entries]


def _read_entry(raw, category, url):
    """Return a source entry holding exactly the nine documented fields."""
    if not isinstance(raw, dict):
        raise SourceError(f"source metadata from {url} has a non-object '{category}' entry")

    for field, kind in ENTRY_FIELD_TYPES.items():
        if field not in raw:
            raise SourceError(f"'{category}' entry in {url} is missing the '{field}' field")
        if not _has_type(raw[field], kind):
            raise SourceError(f"'{category}' entry in {url} has a '{field}' field of the wrong type")

    entry = {field: raw[field] for field in ENTRY_FIELD_TYPES}
    try:
        entry["published"] = normalize_datetime(entry["published"])
    except ValueError:
        raise SourceError(f"'{category}' entry in {url} has an unreadable 'published' value") from None
    return entry


def _has_type(value, kind):
    """Type check that keeps JSON booleans out of integer fields."""
    return isinstance(value, kind) and not isinstance(value, bool)
