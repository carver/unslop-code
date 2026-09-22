"""Supported catalog versions and the upgrade of legacy layouts to the v3 shape.

Version 1 and version 2 catalogs are read directly: they are converted to the
native version 3 shape in memory, so every command sees one representation and
nothing is written to disk until a command has a reason to write.
"""

from datetime import datetime, timezone

from mvaultlib.entries import CATEGORIES, SOURCE_TRACKED_FIELDS
from mvaultlib.errors import MvaultError
from mvaultlib.timestamps import format_timestamp

NATIVE_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, NATIVE_VERSION)

#: How a version 1 `source_id` is turned into a full source URL.
V1_SOURCE_URL = "https://media.example.com/channel/{}"


def upgrade_catalog(name, catalog, timestamp):
    """Return the version found on disk and the catalog in the native v3 shape.

    A v3 catalog is returned as it is, so re-reading one adds no history entry
    and changes nothing. `timestamp` dates the `removed` history that migration
    adds to every legacy entry.
    """
    version = detect_version(name, catalog)
    if version == NATIVE_VERSION:
        return version, catalog
    upgrade = _upgrade_v1 if version == 1 else _upgrade_v2
    return version, upgrade(name, catalog, timestamp)


def detect_version(name, catalog):
    """Read the `version` field, rejecting catalogs mvault cannot represent."""
    if not isinstance(catalog, dict):
        raise MvaultError(f"vault '{name}' has an invalid catalog: root is not an object")
    if "version" not in catalog:
        raise MvaultError(f"vault '{name}' has an invalid catalog: no 'version' field")
    version = catalog["version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise MvaultError(f"vault '{name}' has an invalid catalog version: 'version' must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise MvaultError(
            f"vault '{name}' has an unsupported catalog version {version}: "
            f"supported versions are {', '.join(str(known) for known in SUPPORTED_VERSIONS)}"
        )
    return version


def _upgrade_v1(name, catalog, timestamp):
    """Derive the source URL and move the flat `entries` list into `episodes`."""
    source_id = catalog.get("source_id")
    if not isinstance(source_id, str):
        raise MvaultError(f"vault '{name}' has an invalid v1 catalog: 'source_id' must be a string")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise MvaultError(f"vault '{name}' has an invalid v1 catalog: 'entries' must be an array")

    label = f"vault '{name}' invalid v1 catalog: entries"
    upgraded = {"version": NATIVE_VERSION, "source": V1_SOURCE_URL.format(source_id)}
    upgraded["episodes"] = [_upgrade_entry(entry, _from_epoch_key, label, timestamp) for entry in entries]
    upgraded["streams"] = []
    upgraded["clips"] = []
    return upgraded


def _upgrade_v2(name, catalog, timestamp):
    """Keep the source and the category placement; only the entries gain fields."""
    upgraded = dict(catalog)
    upgraded["version"] = NATIVE_VERSION
    for category in CATEGORIES:
        label = f"vault '{name}' invalid v2 catalog: {category}"
        # v2 history keys are already ISO 8601 text, so `str` leaves them alone.
        upgraded[category] = [
            _upgrade_entry(entry, str, label, timestamp) for entry in catalog.get(category, [])
        ]
    return upgraded


def _upgrade_entry(entry, convert_key, label, timestamp):
    """Return one legacy entry in v3 shape: converted keys plus the local fields."""
    if not isinstance(entry, dict):
        raise MvaultError(f"{label} entry is not an object")
    upgraded = dict(entry)
    for field in SOURCE_TRACKED_FIELDS:
        upgraded[field] = _upgrade_history(entry.get(field), convert_key, f"{label} entry field '{field}'")
    upgraded["removed"] = {timestamp: False}
    upgraded["annotations"] = []
    return upgraded


def _upgrade_history(history, convert_key, label):
    """Rewrite the keys of one tracked-field history, keeping its values."""
    if not isinstance(history, dict) or not history:
        raise MvaultError(f"{label} is not a non-empty history object")
    try:
        return {convert_key(key): value for key, value in history.items()}
    except ValueError as error:
        raise MvaultError(f"{label} has an unreadable datetime key: {error}") from error


def _from_epoch_key(key):
    """Turn UNIX-epoch seconds text into canonical datetime text read as UTC."""
    return format_timestamp(datetime.fromtimestamp(int(key), tz=timezone.utc))
