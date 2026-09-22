"""Fetching and validating media-platform metadata from a vault's source URL."""

import json
import urllib.request

from .timestamps import normalize_timestamp

CATEGORIES = ("episodes", "streams", "clips")
#: Path a source platform serves an entry's own page under.
ENTRY_PATH = "entry"


class SourceError(Exception):
    """Raised when source metadata cannot be fetched or fails schema checks."""


def _is_text(value):
    return isinstance(value, str)


def _is_count(value):
    # ``bool`` is a subclass of ``int`` but is not a valid count.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_optional_count(value):
    return value is None or _is_count(value)


FIELD_VALIDATORS = {
    "id": _is_text,
    "published": _is_text,
    "width": _is_count,
    "height": _is_count,
    "title": _is_text,
    "description": _is_text,
    "views": _is_count,
    "likes": _is_optional_count,
    "preview": _is_text,
}


def resource_url(source, path, name):
    """URL of one resource the source offers below its ``source`` URL.

    Assets are fetched from here during a sync, and the viewer derives the
    source-platform link of an entry from the same shape.
    """
    return f"{source.rstrip('/')}/{path}/{name}"


def fetch(url):
    """Return the current source snapshot as ``{category: [entry, ...]}``.

    Raises :class:`SourceError` for transport problems, unparseable JSON, a
    payload that is not an object holding the three category arrays, or any
    entry that does not match the source entry schema.
    """
    try:
        with urllib.request.urlopen(url) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise SourceError(f"could not read {url}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceError("source payload is not a JSON object")
    return {category: _read_category(payload, category) for category in CATEGORIES}


def _read_category(payload, category):
    """Validate one category array of the payload."""
    listing = payload.get(category)
    if not isinstance(listing, list):
        raise SourceError(f"source payload has no {category} array")
    return [_read_entry(entry, category) for entry in listing]


def _read_entry(entry, category):
    """Validate a source entry and return it with a normalized ``published``."""
    if not isinstance(entry, dict):
        raise SourceError(f"{category} holds an entry that is not a JSON object")
    for field, is_valid in FIELD_VALIDATORS.items():
        if field not in entry:
            raise SourceError(f"{category} entry is missing the {field} field")
        if not is_valid(entry[field]):
            raise SourceError(f"{category} entry has an invalid {field} field")
    checked = {field: entry[field] for field in FIELD_VALIDATORS}
    try:
        checked["published"] = normalize_timestamp(checked["published"])
    except ValueError as error:
        raise SourceError(f"{category} entry {checked['id']} has an invalid published field") from error
    return checked
