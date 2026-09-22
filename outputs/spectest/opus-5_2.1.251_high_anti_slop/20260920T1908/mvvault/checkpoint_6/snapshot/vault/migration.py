"""Reading catalogs written by older versions of mvault.

Version 1 and version 2 catalogs are converted to the version 3 layout as they
are read, so every command sees the same in-memory shape. Conversion never
touches the stored file; persisting the result is the caller's decision.
"""

from datetime import datetime

from .errors import VaultError
from .schema import (
    ANNOTATIONS_FIELD,
    CATEGORIES,
    STATIC_FIELDS,
    TRACKED_FIELDS,
    VERSION,
    matches_type,
)
from .timestamps import format_epoch, format_timestamp, normalize_published

LEGACY_SOURCE_PREFIX = "https://media.example.com/channel/"


def upgrade(catalog: dict, moment: datetime) -> dict:
    """Return ``catalog`` in the version 3 layout, leaving the original as it is.

    A version 3 catalog is handed back unchanged. Older ones are rebuilt, with
    ``moment`` as the timestamp of the ``removed: false`` history the layout
    adds to each entry.
    """
    version = _version(catalog)
    if version == VERSION:
        return catalog
    return _UPGRADES[version](catalog, moment)


def _version(catalog: dict) -> int:
    """Return the version of a stored catalog, rejecting ones mvault cannot read."""
    if "version" not in catalog:
        raise VaultError("catalog has no 'version' field")
    version = catalog["version"]
    if not matches_type(version, int):
        raise VaultError(f"catalog has a non-integer version {version!r}")
    if version not in _UPGRADES and version != VERSION:
        raise VaultError(f"catalog version {version} is not supported; {VERSION} is the newest")
    return version


def _from_version_1(catalog: dict, moment: datetime) -> dict:
    """Rebuild a flat version 1 catalog as categorized version 3 data.

    Version 1 knows only a platform identifier and a single entry list, so the
    source URL is derived and every entry becomes an episode.
    """
    source_id = catalog.get("source_id")
    if not isinstance(source_id, str):
        raise VaultError("version 1 catalog has no 'source_id'")
    upgraded = {"version": VERSION, "source": LEGACY_SOURCE_PREFIX + source_id}
    upgraded.update({category: [] for category in CATEGORIES})
    upgraded["episodes"] = _upgraded_entries(catalog, "entries", format_epoch, moment)
    return upgraded


def _from_version_2(catalog: dict, moment: datetime) -> dict:
    """Rebuild a version 2 catalog as version 3 data, keeping source and categories."""
    source = catalog.get("source")
    if not isinstance(source, str):
        raise VaultError("version 2 catalog has no source URL")
    upgraded = {"version": VERSION, "source": source}
    for category in CATEGORIES:
        upgraded[category] = _upgraded_entries(catalog, category, normalize_published, moment)
    return upgraded


_UPGRADES = {1: _from_version_1, 2: _from_version_2}


def _upgraded_entries(catalog: dict, category: str, key_text, moment: datetime) -> list:
    """Convert one legacy entry array, named ``category`` in the stored catalog."""
    entries = catalog.get(category)
    if not isinstance(entries, list):
        raise VaultError(f"legacy catalog has no '{category}' array")
    return [_upgraded_entry(entry, category, key_text, moment) for entry in entries]


def _upgraded_entry(entry, category: str, key_text, moment: datetime) -> dict:
    """Restate a legacy entry with vault history keys, ``removed`` and ``annotations``."""
    if not isinstance(entry, dict):
        raise VaultError(f"legacy catalog has an item in '{category}' that is not an object")
    values = {
        field: _field_value(entry, field, expected, category)
        for field, expected in STATIC_FIELDS.items()
    }
    upgraded = {**values, "published": _published_text(values["published"], category)}
    for field, expected in TRACKED_FIELDS.items():
        upgraded[field] = _upgraded_history(entry, field, expected, category, key_text)
    upgraded["removed"] = {format_timestamp(moment): False}
    upgraded[ANNOTATIONS_FIELD] = []
    return upgraded


def _upgraded_history(entry: dict, field: str, expected, category: str, key_text) -> dict:
    """Convert one history object, rewriting its keys as vault datetime text.

    The result is ordered by key so that a migrated history reads in the same
    chronological order as one mvault appended itself.
    """
    history = _field_value(entry, field, dict, category)
    if not history:
        raise VaultError(
            f"legacy catalog has a '{category}' entry with an empty '{field}' history"
        )
    upgraded = {}
    for key, value in history.items():
        if not matches_type(value, expected):
            raise VaultError(
                f"legacy catalog has a '{category}' entry with a '{field}' value of the wrong type"
            )
        upgraded[_converted_key(key, field, category, key_text)] = value
    return dict(sorted(upgraded.items()))


def _converted_key(key: str, field: str, category: str, key_text) -> str:
    try:
        return key_text(key)
    except ValueError as error:
        raise VaultError(
            f"legacy catalog has a '{category}' entry with an unreadable '{field}' key {key!r}"
        ) from error


def _published_text(published: str, category: str) -> str:
    try:
        return normalize_published(published)
    except ValueError as error:
        raise VaultError(
            f"legacy catalog has a '{category}' entry with an unreadable 'published': {published!r}"
        ) from error


def _field_value(entry: dict, field: str, expected, category: str):
    """Read a legacy entry field, rejecting a missing one or one of the wrong type."""
    if field not in entry:
        raise VaultError(
            f"legacy catalog has a '{category}' entry missing the '{field}' field"
        )
    value = entry[field]
    if not matches_type(value, expected):
        raise VaultError(
            f"legacy catalog has a '{category}' entry with a '{field}' field of the wrong type"
        )
    return value
