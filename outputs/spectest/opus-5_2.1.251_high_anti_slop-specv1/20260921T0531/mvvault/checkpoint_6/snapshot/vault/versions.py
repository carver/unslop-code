"""Catalog schema versions and the upgrade of legacy layouts to the native one.

Version 1 holds every entry in a single ``entries`` list under a short
``source_id`` and keys its histories by UNIX epoch seconds. Version 2 already
uses the category arrays, the full ``source`` URL and ISO 8601 history keys but
predates the ``removed`` and ``annotations`` fields. Version 3, the native
layout, adds both.

Upgrading happens in memory: every command reads a legacy vault as if it were
native, and only a command that writes puts the upgraded catalog on disk.
"""

from datetime import datetime

from . import entries
from .errors import VaultError
from .source import CATEGORIES
from .timestamps import format_timestamp, from_epoch, normalize_timestamp

VERSION = 3
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{}"


def detect(name, catalog):
    """Return the schema version of ``catalog``, rejecting unsupported ones."""
    if not isinstance(catalog, dict):
        raise VaultError(f"vault {name} has a catalog that is not a JSON object")
    version = catalog.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise VaultError(f"vault {name} has a missing or non-integer catalog version")
    if not 1 <= version <= VERSION:
        raise VaultError(f"vault {name} has an unsupported catalog version: {version}")
    return version


def upgrade(name, catalog):
    """Return the native form of the version 1 or 2 catalog ``catalog``.

    Every entry gains an ``annotations`` list and a ``removed`` history whose
    single point says the entry was offered at the moment of the upgrade.
    """
    stamp = format_timestamp(datetime.now())
    if catalog["version"] == 1:
        return _from_v1(name, catalog, stamp)
    return _from_v2(name, catalog, stamp)


def _from_v1(name, catalog, stamp):
    """Upgrade a version 1 catalog: derive the source, fill the categories."""
    if not isinstance(catalog.get("source_id"), str):
        raise VaultError(f"vault {name} has no source id")
    listing = catalog.get("entries")
    if not isinstance(listing, list):
        raise VaultError(f"vault {name} is missing the entries array")
    return {
        "version": VERSION,
        "source": V1_SOURCE_TEMPLATE.format(catalog["source_id"]),
        "episodes": [_upgrade_entry(name, entry, from_epoch, stamp) for entry in listing],
        "streams": [],
        "clips": [],
    }


def _from_v2(name, catalog, stamp):
    """Upgrade a version 2 catalog: keep the source and category placement."""
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault {name} has no source URL")
    upgraded = {"version": VERSION, "source": catalog["source"]}
    for category in CATEGORIES:
        listing = catalog.get(category)
        if not isinstance(listing, list):
            raise VaultError(f"vault {name} is missing the {category} array")
        upgraded[category] = [
            _upgrade_entry(name, entry, normalize_timestamp, stamp) for entry in listing
        ]
    return upgraded


def _upgrade_entry(name, entry, convert_key, stamp):
    """Return one legacy entry in native form, rejecting malformed input.

    ``convert_key`` maps a legacy history key to stored timestamp text.
    """
    if not isinstance(entry, dict):
        raise VaultError(f"vault {name} holds a legacy entry that is not a JSON object")
    missing = [field for field in entries.STATIC_FIELDS if field not in entry]
    if missing:
        raise VaultError(f"vault {name} holds a legacy entry with no {', '.join(missing)} field(s)")
    upgraded = {field: entry[field] for field in entries.STATIC_FIELDS}
    upgraded.update({
        field: _upgrade_history(name, entry.get(field), field, convert_key)
        for field in entries.TRACKED_FIELDS
    })
    upgraded[entries.REMOVED_FIELD] = {stamp: False}
    upgraded[entries.ANNOTATIONS_FIELD] = []
    return upgraded


def _upgrade_history(name, values, field, convert_key):
    """Return one legacy history with its keys converted to timestamp text."""
    if not isinstance(values, dict):
        raise VaultError(f"vault {name} holds a legacy entry with an invalid {field} history")
    try:
        return {convert_key(key): value for key, value in values.items()}
    except ValueError as error:
        raise VaultError(
            f"vault {name} holds a legacy entry with an unreadable {field} timestamp"
        ) from error
