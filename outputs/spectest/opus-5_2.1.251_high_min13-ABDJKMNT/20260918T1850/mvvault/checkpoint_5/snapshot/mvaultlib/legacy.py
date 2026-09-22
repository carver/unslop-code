"""Reading version 1 and version 2 catalogs, and converting them to version 3.

A legacy catalog is converted into a brand-new v3 catalog rather than patched in
place, so a malformed entry half-way through aborts the run with nothing written
and the caller decides whether the result is ever saved.
"""

from datetime import datetime

from .catalog import CATEGORIES, VERSION, validate_catalog
from .entries import STATIC_VALIDATORS
from .history import SOURCE_TRACKED_FIELDS, VALUE_VALIDATORS, is_integer, is_text
from .timestamps import epoch_to_iso, format_datetime

#: Catalog versions this tool can read.
SUPPORTED_VERSIONS = (1, 2, 3)

#: A v1 catalog stores only a short platform id; its full URL is derived from it.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{}"


def load_catalog(data):
    """Return `data` as a v3 catalog, plus whether migration was needed.

    Raises ValueError for an unreadable `version`, an unusable legacy layout, or
    a malformed legacy entry.
    """
    version = read_version(data)
    if version == VERSION:
        validate_catalog(data)
        return data, False

    timestamp = format_datetime(datetime.now())
    migrate = _from_v1 if version == 1 else _from_v2
    return migrate(data, timestamp), True


def read_version(data):
    """The declared version: the only field read before the layout is known."""
    if not isinstance(data, dict):
        raise ValueError("catalog is not a JSON object")
    if "version" not in data:
        raise ValueError("catalog has no 'version' field")

    version = data["version"]
    if not is_integer(version):
        raise ValueError(f"catalog 'version' is not an integer: {version!r}")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported catalog version {version}")
    return version


def _from_v1(data, timestamp):
    """Convert the flat v1 layout: derived source, every entry an episode."""
    source_id = data.get("source_id")
    if not is_text(source_id):
        raise ValueError("version 1 catalog has no usable 'source_id'")

    return {
        "version": VERSION,
        "source": V1_SOURCE_TEMPLATE.format(source_id),
        "episodes": _migrate_category(data, "entries", epoch_to_iso, timestamp),
        "streams": [],
        "clips": [],
    }


def _from_v2(data, timestamp):
    """Convert the v2 layout: source and category placement are kept as they are."""
    source = data.get("source")
    if not is_text(source):
        raise ValueError("version 2 catalog has no usable source URL")

    catalog = {"version": VERSION, "source": source}
    for category in CATEGORIES:
        catalog[category] = _migrate_category(data, category, _iso_key, timestamp)
    return catalog


def _migrate_category(data, key, convert_key, timestamp):
    """Migrate one legacy entry array, named `key` in the legacy catalog."""
    entries = data.get(key)
    if not isinstance(entries, list):
        raise ValueError(f"catalog field {key!r} is missing or not an array")
    return [
        _migrate_entry(entry, f"{key}[{position}]", convert_key, timestamp)
        for position, entry in enumerate(entries)
    ]


def _migrate_entry(entry, where, convert_key, timestamp):
    """One legacy entry as a v3 entry: histories re-keyed, local fields added.

    Fields this tool does not know about are carried across untouched.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"entry {where} is not an object")
    _validate_static_fields(entry, where)

    histories = {
        field: _migrate_history(entry, field, where, convert_key)
        for field in SOURCE_TRACKED_FIELDS
    }
    return {**entry, **histories, "removed": {timestamp: False}, "annotations": []}


def _validate_static_fields(entry, where):
    """Check the four fields a legacy entry carries without history."""
    for field, is_valid in STATIC_VALIDATORS.items():
        if field not in entry:
            raise ValueError(f"entry {where} is missing the {field!r} field")
        if not is_valid(entry[field]):
            raise ValueError(f"entry {where} has a {field!r} value of the wrong type")


def _migrate_history(entry, field, where, convert_key):
    """Validate one legacy history and return it keyed by ISO 8601 text."""
    history = entry.get(field)
    if not isinstance(history, dict):
        raise ValueError(f"entry {where} is missing the {field!r} history object")

    is_valid = VALUE_VALIDATORS[field]
    converted = {}
    for key, value in history.items():
        if not is_valid(value):
            raise ValueError(f"entry {where} has a {field!r} value of the wrong type at {key!r}")
        try:
            converted[convert_key(key)] = value
        except (ValueError, OverflowError) as error:
            raise ValueError(
                f"entry {where} has an unusable {field!r} history key {key!r}"
            ) from error
    return dict(sorted(converted.items()))


def _iso_key(key):
    """A v2 key, checked to be ISO 8601 and kept exactly as stored."""
    datetime.fromisoformat(key)
    return key
