"""Reading media metadata from a vault's source URL."""

import requests

from .catalog import CATEGORIES
from .timestamps import normalize_published

REQUEST_TIMEOUT = 30

SOURCE_FIELDS = {
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


class SourceError(Exception):
    """Raised when source metadata cannot be fetched or cannot be trusted."""


def fetch_source(url: str) -> dict:
    """Return ``{category: [entry, ...]}`` as published by ``url``.

    Entries keep their source fields, with ``published`` normalized to vault
    datetime text. Any unusable response or entry aborts the whole fetch.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise SourceError(f"could not fetch source metadata from {url}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceError(f"source metadata from {url} is not a JSON object")
    return {category: _validated_entries(payload.get(category), category) for category in CATEGORIES}


def _validated_entries(entries, category: str) -> list:
    """Validate one category array from a source response."""
    if not isinstance(entries, list):
        raise SourceError(f"source metadata has no '{category}' array")
    return [_validated_entry(entry, category) for entry in entries]


def _validated_entry(entry, category: str) -> dict:
    """Check that a source entry carries every required field, with its type."""
    if not isinstance(entry, dict):
        raise SourceError(f"source metadata has a '{category}' item that is not an object")
    for field, expected in SOURCE_FIELDS.items():
        if field not in entry:
            raise SourceError(f"source {category} entry is missing the '{field}' field")
        if not _matches_type(entry[field], expected):
            raise SourceError(f"source {category} entry has a '{field}' field of the wrong type")
    return {**entry, "published": _published_text(entry, category)}


def _published_text(entry: dict, category: str) -> str:
    try:
        return normalize_published(entry["published"])
    except ValueError as error:
        raise SourceError(
            f"source {category} entry has an unreadable 'published' value: {entry['published']!r}"
        ) from error


def _matches_type(value, expected) -> bool:
    """No source field accepts a boolean, which ``isinstance`` would read as an int."""
    return not isinstance(value, bool) and isinstance(value, expected)
