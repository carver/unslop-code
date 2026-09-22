"""Fetching and validating the media-platform source document."""

import json
import urllib.request

from .errors import SourceError

CATEGORIES = ("episodes", "streams", "clips")

# The nine fields every source entry must carry, with their JSON types.
ENTRY_FIELDS = {
    "id": (str,),
    "published": (str,),
    "width": (int,),
    "height": (int,),
    "title": (str,),
    "description": (str,),
    "views": (int,),
    "likes": (int, type(None)),
    "preview": (str,),
}


def has_type(value, types):
    """JSON-faithful type test.

    `bool` is a subclass of `int` in Python, but JSON `true` is not an integer,
    so booleans are rejected wherever a number is required.
    """
    return not isinstance(value, bool) and isinstance(value, types)


def fetch_source(url):
    """GET `url` and return its validated `{category: [entry, ...]}` payload.

    Every way of not getting usable metadata — transport errors, error
    statuses, unparseable or mis-shaped documents, malformed entries — raises
    `SourceError`.
    """
    try:
        with urllib.request.urlopen(url) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceError(f"could not read {url}: {exc}") from exc

    return validate_document(document)


def validate_document(document):
    """Check the response envelope and every entry it carries."""
    if not isinstance(document, dict):
        raise SourceError("source response is not a JSON object")

    payload = {}
    for category in CATEGORIES:
        entries = document.get(category)
        if not isinstance(entries, list):
            raise SourceError(f"source response has no '{category}' array")
        for entry in entries:
            validate_entry(entry, category)
        payload[category] = entries
    return payload


def validate_entry(entry, category):
    """Check that one source entry carries all nine fields with right types."""
    if not isinstance(entry, dict):
        raise SourceError(f"{category} entry is not a JSON object")

    for field, types in ENTRY_FIELDS.items():
        if field not in entry:
            raise SourceError(f"{category} entry is missing '{field}'")
        if not has_type(entry[field], types):
            raise SourceError(f"{category} entry has a {field} of the wrong type")
