"""Catalog version detection and upgrade to the native version 3 layout.

Vaults written by older mvault releases stay readable: every command turns the
stored catalog into a native one with :func:`upgrade` before using it.  The
upgrade happens in memory, so a command that only reads a vault leaves its
legacy ``catalog.json`` untouched; persisting the result is the caller's call.

| Version | Layout |
|---|---|
| 1 | flat ``entries`` list, ``source_id``, UNIX-epoch history keys |
| 2 | category arrays, ``source``, ISO 8601 history keys |
| 3 | version 2 plus the ``removed`` history and ``annotations`` |
"""

from datetime import datetime
from typing import Any, Callable

import catalogs
from catalogs import Catalog, Entry
from errors import MvaultError
from timestamps import format_timestamp, from_epoch, normalize_iso

#: Source URL a version 1 vault stands for, given its short platform id.
V1_SOURCE = "https://media.example.com/channel/{source_id}"

#: Converts a stored history key of one legacy version to canonical text.
KeyConverter = Callable[[str], str]


def upgrade(catalog: Any, name: str) -> Catalog:
    """Return the catalog of vault ``name`` in the native version 3 shape.

    Structural problems of the stored version, including an unsupported
    version field, are reported as user-facing failures.
    """
    return _UPGRADES[_version(catalog, name)](catalog, name)


def is_native(catalog: Catalog) -> bool:
    """True when the stored catalog needs no upgrade to be used."""
    return catalog["version"] == catalogs.CATALOG_VERSION


def _version(catalog: Any, name: str) -> int:
    """Read the version a stored catalog declares, rejecting unusable ones."""
    if not isinstance(catalog, dict) or "version" not in catalog:
        raise MvaultError(f"Vault '{name}' has a catalog without a version")
    version = catalog["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise MvaultError(f"Vault '{name}' has a non-integer catalog version: {version!r}")
    if version not in _UPGRADES:
        raise MvaultError(
            f"Vault '{name}' has catalog version {version}, "
            f"but mvault supports up to version {catalogs.CATALOG_VERSION}"
        )
    return version


def _native(catalog: Catalog, name: str) -> Catalog:
    """Check a version 3 catalog, which is already in the native shape."""
    well_formed = isinstance(catalog.get("source"), str) and all(
        isinstance(catalog.get(category), list) for category in catalogs.CATEGORIES
    )
    if not well_formed:
        raise MvaultError(f"Vault '{name}' has an invalid catalog")
    return catalog


def _from_v1(catalog: Catalog, name: str) -> Catalog:
    """Upgrade a version 1 catalog: one flat list under a short source id."""
    source_id = catalog.get("source_id")
    if not isinstance(source_id, str):
        raise MvaultError(f"Vault '{name}' has a catalog without a source id")
    native: Catalog = {
        "version": catalogs.CATALOG_VERSION,
        "source": V1_SOURCE.format(source_id=source_id),
    }
    native.update({category: [] for category in catalogs.CATEGORIES})
    native["episodes"] = _entries(
        catalog.get("entries"), f"'{name}' entries", from_epoch, format_timestamp(datetime.now())
    )
    return native


def _from_v2(catalog: Catalog, name: str) -> Catalog:
    """Upgrade a version 2 catalog, which already has the native layout."""
    source = catalog.get("source")
    if not isinstance(source, str):
        raise MvaultError(f"Vault '{name}' has a catalog without a source")
    native: Catalog = {"version": catalogs.CATALOG_VERSION, "source": source}
    moment = format_timestamp(datetime.now())
    native.update(
        {
            category: _entries(
                catalog.get(category), f"'{name}' {category}", normalize_iso, moment
            )
            for category in catalogs.CATEGORIES
        }
    )
    return native


def _entries(entries: Any, label: str, convert_key: KeyConverter, moment: str) -> list[Entry]:
    """Upgrade one stored category of entries."""
    if not isinstance(entries, list):
        raise MvaultError(f"Catalog {label} is not an array")
    return [
        _entry(entry, f"{label}[{position}]", convert_key, moment)
        for position, entry in enumerate(entries)
    ]


def _entry(entry: Any, label: str, convert_key: KeyConverter, moment: str) -> Entry:
    """Rebuild one legacy entry, adding the fields its version never had.

    Legacy entries were never marked removed, so the upgraded entry starts a
    ``removed`` history saying so as of the migration ``moment``.
    """
    if not isinstance(entry, dict):
        raise MvaultError(f"Catalog {label} is not an object")
    native = {field: _static(entry, field, label) for field in catalogs.STATIC_FIELDS}
    native.update(
        {
            field: _history(
                entry.get(field), f"{label} '{field}'", catalogs.FIELD_TYPES[field], convert_key
            )
            for field in catalogs.SOURCE_TRACKED_FIELDS
        }
    )
    native["removed"] = {moment: False}
    native["annotations"] = []
    return native


def _static(entry: dict, field: str, label: str) -> Any:
    """Take one untracked field of a legacy entry."""
    value = entry.get(field)
    if isinstance(value, bool) or not isinstance(value, catalogs.FIELD_TYPES[field]):
        raise MvaultError(f"Catalog {label} has an invalid '{field}'")
    return value


def _history(
    values: Any, label: str, types: tuple[type, ...], convert_key: KeyConverter
) -> dict[str, Any]:
    """Take one tracked field of a legacy entry, converting its keys."""
    if not isinstance(values, dict):
        raise MvaultError(f"Catalog {label} is not a history object")
    for value in values.values():
        if isinstance(value, bool) or not isinstance(value, types):
            raise MvaultError(f"Catalog {label} has an invalid value")
    try:
        return {convert_key(key): value for key, value in values.items()}
    except (OSError, OverflowError, ValueError) as error:
        raise MvaultError(f"Catalog {label} has an unreadable timestamp: {error}") from error


#: The upgrade each supported stored version needs, keyed by version number.
_UPGRADES: dict[int, Callable[[Catalog, str], Catalog]] = {
    1: _from_v1,
    2: _from_v2,
    catalogs.CATALOG_VERSION: _native,
}
