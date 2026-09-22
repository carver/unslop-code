"""Fetching and validating the source metadata document."""

import json
import urllib.request

from mvaultlib.catalog import CATEGORIES
from mvaultlib.errors import MvaultError

FETCH_FAILURE = "Source metadata fetch failure"

#: Required source entry fields and the JSON types they accept.
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


class SourceError(MvaultError):
    """Any reason the source metadata could not be used."""

    def __init__(self, detail):
        super().__init__(f"{FETCH_FAILURE}: {detail}")


def fetch_source(url):
    """GET the source URL and return its validated `{category: entries}` map."""
    try:
        with urllib.request.urlopen(url) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError) as error:
        raise SourceError(f"could not read {url}: {error}") from error
    return _validate_payload(payload)


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise SourceError("response is not a JSON object")
    categories = {}
    for category in CATEGORIES:
        entries = payload.get(category)
        if not isinstance(entries, list):
            raise SourceError(f"'{category}' is missing or not an array")
        for entry in entries:
            _validate_entry(category, entry)
        categories[category] = entries
    return categories


def _validate_entry(category, entry):
    if not isinstance(entry, dict):
        raise SourceError(f"{category} entry is not an object")
    for field, expected in ENTRY_FIELDS.items():
        if field not in entry:
            raise SourceError(f"{category} entry is missing field '{field}'")
        if not _has_type(entry[field], expected):
            raise SourceError(f"{category} entry field '{field}' has the wrong type")


def _has_type(value, expected):
    """JSON booleans are not integers, even though Python's `bool` is."""
    if isinstance(value, bool):
        return False
    return isinstance(value, expected)
