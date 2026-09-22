"""Fetching and validating media-platform metadata from a vault source URL."""

import json
import urllib.request
from typing import Any

from catalogs import CATEGORIES
from errors import MvaultError

FETCH_FAILURE = "Source metadata fetch failure"

#: Accepted Python types for each field a source entry must provide.
FIELD_TYPES: dict[str, tuple[type, ...]] = {
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

SourceData = dict[str, list[dict[str, Any]]]


def fetch(url: str) -> SourceData:
    """Download the source document and return its validated categories.

    Any transport, decoding or schema problem is raised as a single fetch
    failure so the caller can leave the vault untouched.
    """
    try:
        with urllib.request.urlopen(url) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise MvaultError(f"{FETCH_FAILURE}: {url}: {error}") from error
    return _validate(document, url)


def _validate(document: Any, url: str) -> SourceData:
    """Check the downloaded document against the source schema."""
    if not isinstance(document, dict):
        raise MvaultError(f"{FETCH_FAILURE}: {url}: expected a JSON object")
    for category in CATEGORIES:
        entries = document.get(category)
        if not isinstance(entries, list):
            raise MvaultError(f"{FETCH_FAILURE}: {url}: missing '{category}' array")
        for position, entry in enumerate(entries):
            _validate_entry(entry, category, position, url)
    return {category: document[category] for category in CATEGORIES}


def _validate_entry(entry: Any, category: str, position: int, url: str) -> None:
    """Check that one source entry carries every required field and type."""
    location = f"{category}[{position}]"
    if not isinstance(entry, dict):
        raise MvaultError(f"{FETCH_FAILURE}: {url}: {location} is not an object")
    for field, types in FIELD_TYPES.items():
        if field not in entry:
            raise MvaultError(f"{FETCH_FAILURE}: {url}: {location} is missing '{field}'")
        value = entry[field]
        if isinstance(value, bool) or not isinstance(value, types):
            raise MvaultError(f"{FETCH_FAILURE}: {url}: {location} has an invalid '{field}'")
