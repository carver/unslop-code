"""Fetching and validating media-platform source metadata."""

import requests

from .catalog import CATEGORIES
from .errors import SourceError
from .history import normalize_published

REQUEST_TIMEOUT = 30

#: Every field a source entry must provide, with its accepted JSON type.
ENTRY_FIELDS = {
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
    """Return source metadata as ``{category: [entry, ...]}`` with published values normalized."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise SourceError(f"could not fetch source metadata from {url}: {error}") from error
    return _read_payload(payload)


def _read_payload(payload):
    """Validate the fetched document and return its entries per category."""
    if not isinstance(payload, dict):
        raise SourceError("source metadata is not a JSON object")
    entries = {}
    for category in CATEGORIES:
        listing = payload.get(category)
        if not isinstance(listing, list):
            raise SourceError(f"source metadata has no '{category}' array")
        entries[category] = [_read_entry(item, category) for item in listing]
    return entries


def _read_entry(item, category):
    """Validate one source entry and return it with a normalized ``published`` value."""
    if not isinstance(item, dict):
        raise SourceError(f"source metadata has a {category} entry that is not an object")
    for field, expected in ENTRY_FIELDS.items():
        if field not in item:
            raise SourceError(f"source metadata has a {category} entry without '{field}'")
        if not _has_type(item[field], expected):
            raise SourceError(f"source metadata has a {category} entry with an invalid '{field}'")
    entry = {field: item[field] for field in ENTRY_FIELDS}
    try:
        entry["published"] = normalize_published(item["published"])
    except ValueError as error:
        raise SourceError(
            f"source metadata has a {category} entry with an unreadable 'published': {error}"
        ) from error
    return entry


def _has_type(value, expected):
    """Check a JSON value against an expected type; booleans never stand in for integers."""
    return isinstance(value, expected) and not isinstance(value, bool)
