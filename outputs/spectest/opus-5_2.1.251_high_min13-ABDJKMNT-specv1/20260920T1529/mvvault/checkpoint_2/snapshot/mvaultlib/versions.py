"""Catalog versions: detecting the on-disk version and reading legacy layouts.

Versions 1 and 2 are read transparently: `upgrade` returns the version 3
representation of a legacy catalog, which is what every command works with.
Persisting that representation is the caller's decision, not this module's.
"""

from .errors import VaultError
from .history import SOURCE_TRACKED_FIELDS
from .source import CATEGORIES, ENTRY_FIELDS, has_type
from .timestamps import checked_datetime, from_epoch, now

VERSION = 3
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{}"

# A legacy entry carries the same nine fields as a source entry, but the five
# tracked ones arrive as histories rather than as bare values.
STATIC_FIELDS = {
    field: types for field, types in ENTRY_FIELDS.items() if field not in SOURCE_TRACKED_FIELDS
}


def detect_version(catalog, name):
    """The catalog's declared version, rejecting anything mvault cannot read."""
    if "version" not in catalog:
        raise VaultError(f"vault '{name}' has a catalog without a version field")

    version = catalog["version"]
    if not has_type(version, (int,)) or not 1 <= version <= VERSION:
        raise VaultError(f"vault '{name}' has an unsupported catalog version: {version!r}")
    return version


def upgrade(catalog, version, name):
    """The version 3 representation of `catalog`, which is at `version`."""
    if version == VERSION:
        return catalog
    return UPGRADES[version](catalog, name, now())


def upgrade_v1(catalog, name, timestamp):
    """Version 1: a flat `entries` list, a `source_id`, and epoch history keys."""
    source_id = require(catalog, "source_id", (str,), name)
    entries = require(catalog, "entries", (list,), name)
    return {
        "version": VERSION,
        "source": V1_SOURCE_TEMPLATE.format(source_id),
        "episodes": [upgrade_entry(entry, from_epoch, timestamp, name) for entry in entries],
        "streams": [],
        "clips": [],
    }


def upgrade_v2(catalog, name, timestamp):
    """Version 2: already categorised and ISO-keyed, but without the v3 fields."""
    upgraded = {"version": VERSION, "source": require(catalog, "source", (str,), name)}
    for category in CATEGORIES:
        entries = require(catalog, category, (list,), name)
        upgraded[category] = [
            upgrade_entry(entry, checked_datetime, timestamp, name) for entry in entries
        ]
    return upgraded


UPGRADES = {1: upgrade_v1, 2: upgrade_v2}


def upgrade_entry(entry, convert_key, timestamp, name):
    """One legacy entry as a v3 entry: re-keyed histories plus the v3 fields.

    `convert_key` renders a legacy history key in the native timestamp format
    and rejects keys that are not in the layout its version promises.
    """
    validate_entry(entry, name)
    upgraded = dict(entry)
    upgraded.update(
        {field: convert_history(entry[field], convert_key, name) for field in SOURCE_TRACKED_FIELDS}
    )
    upgraded["removed"] = {timestamp: False}
    upgraded["annotations"] = []
    return upgraded


def validate_entry(entry, name):
    """Check a legacy entry: four static fields and five non-empty histories."""
    if not isinstance(entry, dict):
        raise VaultError(f"vault '{name}' has a legacy entry that is not a JSON object")

    for field, types in STATIC_FIELDS.items():
        if not has_type(entry.get(field), types):
            raise VaultError(f"vault '{name}' has a legacy entry with a bad '{field}'")

    for field in SOURCE_TRACKED_FIELDS:
        history = entry.get(field)
        if not isinstance(history, dict) or not history:
            raise VaultError(f"vault '{name}' has a legacy entry without a '{field}' history")
        if not all(has_type(value, ENTRY_FIELDS[field]) for value in history.values()):
            raise VaultError(f"vault '{name}' has a legacy entry with a bad '{field}' value")


def convert_history(history, convert_key, name):
    """The same history under native timestamp keys."""
    try:
        return {convert_key(key): value for key, value in history.items()}
    except ValueError as exc:
        raise VaultError(f"vault '{name}' has a legacy entry with a bad history key: {exc}") from exc


def require(catalog, field, types, name):
    """The catalog field a legacy version promises, or a vault error."""
    value = catalog.get(field)
    if not has_type(value, types):
        raise VaultError(f"vault '{name}' has a legacy catalog with a bad '{field}'")
    return value
