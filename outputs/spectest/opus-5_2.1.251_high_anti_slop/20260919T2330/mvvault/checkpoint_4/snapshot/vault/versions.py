"""Catalog version detection, version-native views and migration to the native version.

Version 1 keeps every entry in a flat ``entries`` list, identifies its source by
a short ``source_id`` and stores history keys as UNIX epoch seconds. Version 2
already uses the native category arrays and ISO 8601 history keys but lacks the
``removed`` and ``annotations`` fields.

:func:`view` reads any supported version in its own shape, for commands such as
``digest`` that must not migrate. :func:`to_current` converts such a view to
version 3 so that the writing commands work on one in-memory shape.
"""

from datetime import datetime, timezone
from typing import Callable, NamedTuple

from . import catalog
from .errors import InvalidVaultError
from .history import format_timestamp, parse_timestamp

#: Catalog versions this build understands, newest last.
SUPPORTED_VERSIONS = (1, 2, catalog.VERSION)
#: Source URL of a version 1 vault, derived from its ``source_id``.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"
#: Heading of the single group a version 1 catalog splits into.
V1_LABEL = "Entries"


class CatalogView(NamedTuple):
    """A catalog read in the shape of its own version.

    ``categories`` pairs a display label and the native category name with the
    entry list they hold. ``fields`` lists the history-backed fields that exist
    in this version, and ``key_order`` sorts their timestamp keys: version 1
    compares epoch seconds numerically, later versions compare ISO 8601 text.
    """

    version: int
    source: str
    categories: tuple
    fields: tuple
    key_order: Callable[[str], object]


def load(name):
    """Read the catalog of the vault called ``name`` in the native in-memory format."""
    return to_current(catalog.read_document(name), name)[0]


def view(document, name):
    """Return the :class:`CatalogView` of a catalog document of any supported version."""
    version = version_of(document, name)
    if version == 1:
        return _view_v1(document, name)
    if version == 2:
        return _view_v2(document, name)
    catalog.validate(document, name)
    return CatalogView(version, document["source"], _groups(document), catalog.HISTORY_FIELDS, str)


def to_current(document, name):
    """Return ``(catalog, changed)`` for a catalog document of any supported version.

    ``changed`` tells whether the returned catalog differs from the document on
    disk and therefore has to be written back by a migrating command.
    """
    loaded = view(document, name)
    if loaded.version == catalog.VERSION:
        return document, False
    return _upgrade(loaded, name), True


def latest_value(history, key_order):
    """Return the value a history records at its latest key, in this version's key order."""
    return history[max(history, key=key_order)]


def version_of(document, name):
    """Read the ``version`` field of a catalog document as a supported version number."""
    version = document.get("version")
    if version is None:
        raise InvalidVaultError(f"vault '{name}' has a {catalog.CATALOG_NAME} without a version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise InvalidVaultError(f"vault '{name}' has a non-integer catalog version: {version!r}")
    if version not in SUPPORTED_VERSIONS:
        raise InvalidVaultError(f"vault '{name}' has an unsupported catalog version: {version}")
    return version


def _view_v1(document, name):
    """View a version 1 catalog: source derived from ``source_id``, one flat entry group."""
    source_id = document.get("source_id")
    if not isinstance(source_id, str):
        raise InvalidVaultError(f"vault '{name}' has no source id")
    entries = _entry_list(document, "entries", name)
    _validate_entries(entries, name, "entries")
    return CatalogView(
        version=1,
        source=V1_SOURCE_TEMPLATE.format(source_id=source_id),
        categories=((V1_LABEL, catalog.CATEGORIES[0], entries),),
        fields=catalog.TRACKED_FIELDS,
        key_order=int,
    )


def _view_v2(document, name):
    """View a version 2 catalog: native categories and ISO keys, but no ``removed`` field."""
    source_url = document.get("source")
    if not isinstance(source_url, str):
        raise InvalidVaultError(f"vault '{name}' has no source URL")
    for category in catalog.CATEGORIES:
        _validate_entries(_entry_list(document, category, name), name, category)
    return CatalogView(2, source_url, _groups(document), catalog.TRACKED_FIELDS, str)


def _groups(document):
    """Pair each native category of a categorized catalog with its display label."""
    return tuple(
        (category.capitalize(), category, document[category]) for category in catalog.CATEGORIES
    )


def _entry_list(document, key, name):
    """Return the entry list stored under ``key``, rejecting a missing or malformed one."""
    entries = document.get(key)
    if not isinstance(entries, list):
        raise InvalidVaultError(f"vault '{name}' has no '{key}' list")
    return entries


def _validate_entries(entries, name, category):
    """Check every legacy entry against the schema of the fields its version provides."""
    for entry in entries:
        catalog.validate_entry(entry, name, category, catalog.TRACKED_FIELDS)


def _upgrade(legacy, name):
    """Build a native catalog from a legacy view, converting its history keys."""
    upgraded = catalog.new_catalog(legacy.source)
    moment = format_timestamp(datetime.now().replace(microsecond=0))
    convert = _iso_from_epoch if legacy.version == 1 else _checked_iso
    for label, category, entries in legacy.categories:
        upgraded[category] = [
            _upgrade_entry(entry, name, label, convert, moment) for entry in entries
        ]
    return upgraded


def _upgrade_entry(entry, name, label, convert_key, moment):
    """Rewrite a legacy entry with native history keys, a ``removed`` flag and annotations."""
    upgraded = {field: entry[field] for field in catalog.STATIC_FIELDS}
    try:
        for field in catalog.TRACKED_FIELDS:
            upgraded[field] = {convert_key(key): value for key, value in entry[field].items()}
    except ValueError as error:
        raise InvalidVaultError(
            f"vault '{name}' has a {label.lower()} entry with an unreadable history "
            f"timestamp: {error}"
        ) from error
    upgraded["removed"] = {moment: False}
    upgraded["annotations"] = []
    return upgraded


def _iso_from_epoch(key):
    """Convert a UNIX epoch-seconds history key to an ISO 8601 timestamp in UTC."""
    return format_timestamp(datetime.fromtimestamp(int(key), timezone.utc))


def _checked_iso(key):
    """Return an ISO 8601 history key unchanged, rejecting unreadable text."""
    parse_timestamp(key)
    return key
