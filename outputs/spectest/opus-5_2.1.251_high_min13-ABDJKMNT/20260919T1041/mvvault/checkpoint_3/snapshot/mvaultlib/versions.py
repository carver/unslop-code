"""Reading catalogs of any supported version as the native version 3 layout.

Version 1 keeps every entry in one flat `entries` list, identifies its source
by a short `source_id` and keys history objects by UNIX epoch seconds. Version
2 already uses the native layout but lacks the `removed` and `annotations`
fields. Both are converted in memory, leaving `catalog.json` untouched.
"""

from datetime import datetime, timezone

from .errors import VaultError, VersionError
from .history import SOURCE_TRACKED_FIELDS
from .schema import CATEGORIES, STATIC_FIELD_TYPES, TRACKED_VALUE_TYPES, VERSION, has_type, is_native
from .timestamps import current_stamp, format_datetime

#: How a version 1 `source_id` becomes a full source URL.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"

#: Catalog versions this build can read, native format included.
SUPPORTED_VERSIONS = (1, 2, VERSION)


def to_native(raw, name):
    """Return `(catalog, upgraded)` for the catalog data of the vault `name`.

    `upgraded` says whether `raw` had to be converted, and therefore whether
    the version on disk is out of date.
    """
    version = declared_version(raw, name)
    if version == VERSION:
        if not is_native(raw):
            raise VaultError(f"vault '{name}' has an invalid catalog.json")
        return raw, False
    return _UPGRADES[version](raw, name, current_stamp()), True


def declared_version(raw, name):
    """The version `raw` declares, as one of the versions this build reads."""
    if not isinstance(raw, dict):
        raise VaultError(f"vault '{name}' has an invalid catalog.json")

    version = raw.get("version")
    if version is None:
        raise VersionError(f"vault '{name}' has a catalog.json without a 'version' field")
    if not has_type(version, int) or version not in SUPPORTED_VERSIONS:
        raise VersionError(f"vault '{name}' has an unsupported catalog version: {version!r}")
    return version


def _from_v1(raw, name, stamp):
    """Version 1: a flat entry list under a derived source URL."""
    return {
        "version": VERSION,
        "source": V1_SOURCE_TEMPLATE.format(source_id=text_field(raw, "source_id", name)),
        "episodes": [_upgraded_entry(entry, name, stamp, _from_epoch) for entry in array_field(raw, "entries", name)],
        "streams": [],
        "clips": [],
    }


def _from_v2(raw, name, stamp):
    """Version 2: the native layout, one `removed` and `annotations` short."""
    categories = {
        category: [_upgraded_entry(entry, name, stamp, _checked_iso) for entry in array_field(raw, category, name)]
        for category in CATEGORIES
    }
    return {"version": VERSION, "source": text_field(raw, "source", name), **categories}


_UPGRADES = {1: _from_v1, 2: _from_v2}


def text_field(raw, field, name):
    """A required string at the catalog root, such as `source` or `source_id`."""
    value = raw.get(field)
    if not isinstance(value, str):
        raise VaultError(f"vault '{name}' has a catalog.json without a '{field}' string")
    return value


def array_field(raw, field, name):
    """A required array at the catalog root, such as a category or `entries`."""
    value = raw.get(field)
    if not isinstance(value, list):
        raise VaultError(f"vault '{name}' has a catalog.json without a '{field}' array")
    return value


def _upgraded_entry(entry, name, stamp, to_native_key):
    """A legacy entry plus the two fields version 3 adds to every entry."""
    if not isinstance(entry, dict):
        raise VaultError(f"vault '{name}' has a catalog.json with a non-object entry")

    upgraded = {field: _static_value(entry, field, kind, name) for field, kind in STATIC_FIELD_TYPES.items()}
    upgraded.update({field: _upgraded_history(entry, field, name, to_native_key) for field in SOURCE_TRACKED_FIELDS})
    upgraded["removed"] = {stamp: False}
    upgraded["annotations"] = []
    return upgraded


def _static_value(entry, field, kind, name):
    value = entry.get(field)
    if not has_type(value, kind):
        raise VaultError(f"vault '{name}' has an entry with a missing or mistyped '{field}' field")
    return value


def _upgraded_history(entry, field, name, to_native_key):
    """One history object re-keyed to the native datetime text."""
    history = entry.get(field)
    if not isinstance(history, dict) or not history:
        raise VaultError(f"vault '{name}' has an entry without a '{field}' history")
    if not all(has_type(value, TRACKED_VALUE_TYPES[field]) for value in history.values()):
        raise VaultError(f"vault '{name}' has an entry with a mistyped '{field}' value")

    try:
        return {to_native_key(key): value for key, value in history.items()}
    except ValueError:
        raise VaultError(f"vault '{name}' has an entry with an unreadable '{field}' timestamp") from None


def _from_epoch(key):
    """A version 1 UNIX-epoch seconds key as UTC datetime text."""
    return format_datetime(datetime.fromtimestamp(int(key), tz=timezone.utc))


def _checked_iso(key):
    """A version 2 key: already ISO 8601, so kept exactly as written."""
    datetime.fromisoformat(key)  # rejects anything that is not a datetime
    return key
