"""Catalog version detection and migration of legacy catalogs to the native version.

Version 1 keeps every entry in a flat ``entries`` list, identifies its source by
a short ``source_id`` and stores history keys as UNIX epoch seconds. Version 2
already uses the native category arrays and ISO 8601 history keys but lacks the
``removed`` and ``annotations`` fields. Both are converted to version 3 here so
that every command works on one in-memory shape.
"""

from datetime import datetime, timezone

from . import catalog
from .errors import InvalidVaultError
from .history import format_timestamp, parse_timestamp

#: Catalog versions this build understands, newest last.
SUPPORTED_VERSIONS = (1, 2, catalog.VERSION)
#: Source URL of a version 1 vault, derived from its ``source_id``.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"


def load(name):
    """Read the catalog of the vault called ``name`` in the native in-memory format."""
    return to_current(catalog.read_document(name), name)[0]


def to_current(document, name):
    """Return ``(catalog, changed)`` for a catalog document of any supported version.

    ``changed`` tells whether the returned catalog differs from the document on
    disk and therefore has to be written back by a migrating command.
    """
    version = _version_of(document, name)
    if version == catalog.VERSION:
        catalog.validate(document, name)
        return document, False
    upgrade = {1: _from_v1, 2: _from_v2}[version]
    return upgrade(document, name), True


def _version_of(document, name):
    """Read the ``version`` field of a catalog document as a supported version number."""
    version = document.get("version")
    if version is None:
        raise InvalidVaultError(f"vault '{name}' has a {catalog.CATALOG_NAME} without a version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise InvalidVaultError(f"vault '{name}' has a non-integer catalog version: {version!r}")
    if version not in SUPPORTED_VERSIONS:
        raise InvalidVaultError(f"vault '{name}' has an unsupported catalog version: {version}")
    return version


def _from_v1(document, name):
    """Convert a version 1 catalog: derive the source, fill the categories, convert keys."""
    source_id = document.get("source_id")
    if not isinstance(source_id, str):
        raise InvalidVaultError(f"vault '{name}' has no source id")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise InvalidVaultError(f"vault '{name}' has no 'entries' list")
    upgraded = catalog.new_catalog(V1_SOURCE_TEMPLATE.format(source_id=source_id))
    moment = _migration_timestamp()
    upgraded["episodes"] = [
        _upgrade_entry(entry, name, "entries", _iso_from_epoch, moment) for entry in entries
    ]
    return upgraded


def _from_v2(document, name):
    """Convert a version 2 catalog, keeping its source URL and category placement."""
    source_url = document.get("source")
    if not isinstance(source_url, str):
        raise InvalidVaultError(f"vault '{name}' has no source URL")
    upgraded = catalog.new_catalog(source_url)
    moment = _migration_timestamp()
    for category in catalog.CATEGORIES:
        entries = document.get(category)
        if not isinstance(entries, list):
            raise InvalidVaultError(f"vault '{name}' has no '{category}' list")
        upgraded[category] = [
            _upgrade_entry(entry, name, category, _checked_iso, moment) for entry in entries
        ]
    return upgraded


def _upgrade_entry(entry, name, category, convert_key, moment):
    """Rewrite a legacy entry with native history keys, a ``removed`` flag and annotations."""
    catalog.validate_entry(entry, name, category, catalog.TRACKED_FIELDS)
    upgraded = {field: entry[field] for field in catalog.STATIC_FIELDS}
    try:
        for field in catalog.TRACKED_FIELDS:
            upgraded[field] = {convert_key(key): value for key, value in entry[field].items()}
    except ValueError as error:
        raise InvalidVaultError(
            f"vault '{name}' has a {category} entry with an unreadable history timestamp: {error}"
        ) from error
    upgraded["removed"] = {moment: False}
    upgraded["annotations"] = []
    return upgraded


def _migration_timestamp():
    """Timestamp text recorded as the moment a legacy entry was known to be present."""
    return format_timestamp(datetime.now().replace(microsecond=0))


def _iso_from_epoch(key):
    """Convert a UNIX epoch-seconds history key to an ISO 8601 timestamp in UTC."""
    return format_timestamp(datetime.fromtimestamp(int(key), timezone.utc))


def _checked_iso(key):
    """Return an ISO 8601 history key unchanged, rejecting unreadable text."""
    parse_timestamp(key)
    return key
