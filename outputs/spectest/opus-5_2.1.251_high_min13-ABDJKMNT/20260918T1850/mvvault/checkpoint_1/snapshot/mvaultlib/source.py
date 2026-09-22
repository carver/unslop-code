"""Fetching and validating media metadata from a vault's source URL."""

import requests

from .catalog import CATEGORIES
from .errors import MvaultError
from .timestamps import normalize_published

REQUEST_TIMEOUT = 30


def _is_text(value):
    return isinstance(value, str)


def _is_integer(value):
    """JSON booleans are not integers, even though Python's `bool` subclasses `int`."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_optional_integer(value):
    return value is None or _is_integer(value)


#: The nine fields every source entry must carry, and the values they may hold.
FIELD_VALIDATORS = {
    "id": _is_text,
    "published": _is_text,
    "width": _is_integer,
    "height": _is_integer,
    "title": _is_text,
    "description": _is_text,
    "views": _is_integer,
    "likes": _is_optional_integer,
    "preview": _is_text,
}


def fetch_entries(url):
    """GET the source URL and return validated entries keyed by category.

    Every failure on the way to usable metadata -- transport error, error
    status, unparseable body, wrong response shape, malformed entry -- is
    raised as an MvaultError so the caller can leave the vault untouched.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise MvaultError(f"source metadata fetch failed for {url}: {error}") from error

    if not isinstance(payload, dict):
        raise MvaultError(f"source metadata fetch failed for {url}: response is not a JSON object")
    return {category: _read_category(payload, category) for category in CATEGORIES}


def _read_category(payload, category):
    entries = payload.get(category)
    if not isinstance(entries, list):
        raise MvaultError(f"source metadata is missing the {category!r} array")
    return [_read_entry(entry, category, position) for position, entry in enumerate(entries)]


def _read_entry(entry, category, position):
    """Validate one source entry and normalize its `published` text."""
    where = f"{category}[{position}]"
    if not isinstance(entry, dict):
        raise MvaultError(f"source entry {where} is not an object")

    for field, is_valid in FIELD_VALIDATORS.items():
        if field not in entry:
            raise MvaultError(f"source entry {where} is missing the {field!r} field")
        if not is_valid(entry[field]):
            raise MvaultError(f"source entry {where} has a {field!r} value of the wrong type")

    try:
        published = normalize_published(entry["published"])
    except ValueError as error:
        raise MvaultError(f"source entry {where} has an unparseable 'published' value: {error}") from error

    return {**{field: entry[field] for field in FIELD_VALIDATORS}, "published": published}
