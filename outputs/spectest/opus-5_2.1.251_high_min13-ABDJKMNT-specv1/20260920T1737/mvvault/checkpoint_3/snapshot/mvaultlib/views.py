"""Read-only, version-aware views over a stored catalog.

`digest` reports on v1, v2 and v3 vaults without migrating them, so instead of
upgrading a legacy catalog it reads it in its own shape. A `CatalogView` carries
everything that differs between versions: how entries are grouped, which tracked
fields exist, how history keys are ordered and where the source URL comes from.
"""

from dataclasses import dataclass

from mvaultlib.entries import CATEGORIES, SOURCE_TRACKED_FIELDS, TRACKED_FIELDS
from mvaultlib.errors import MvaultError
from mvaultlib.versions import V1_SOURCE_URL, detect_version

#: Heading shown for each v2/v3 category, and for the single v1 group.
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}
V1_GROUP_LABEL = "Entries"


@dataclass(frozen=True)
class CatalogView:
    """One stored catalog seen through the conventions of its own version."""

    version: int
    source_url: str
    #: `(label, entries)` pairs in the order they should be reported.
    groups: tuple
    tracked_fields: tuple
    #: True when the version records a `removed` flag, so removals are detectable.
    tracks_removal: bool
    #: Key function putting history keys of this version in chronological order.
    key_order: type

    def ordered_keys(self, history):
        """The keys of one tracked-field history, oldest first."""
        return sorted(history, key=self.key_order)

    def current_value(self, history):
        """The value at the latest key of one tracked-field history."""
        return history[self.ordered_keys(history)[-1]]


def build_view(name, catalog):
    """Read `catalog` as a view of whichever supported version it declares."""
    version = detect_version(name, catalog)
    if version == 1:
        return _v1_view(name, catalog)
    return _modern_view(name, catalog, version)


def _v1_view(name, catalog):
    """v1: a flat `entries` list, epoch keys and a source URL built from `source_id`."""
    source_id = catalog.get("source_id")
    if not isinstance(source_id, str):
        raise MvaultError(f"vault '{name}' has an invalid v1 catalog: 'source_id' must be a string")
    entries = _entry_list(name, catalog, "entries", SOURCE_TRACKED_FIELDS)
    return CatalogView(
        version=1,
        source_url=V1_SOURCE_URL.format(source_id),
        groups=((V1_GROUP_LABEL, entries),),
        tracked_fields=SOURCE_TRACKED_FIELDS,
        tracks_removal=False,
        key_order=int,
    )


def _modern_view(name, catalog, version):
    """v2 and v3: per-category groups, ISO 8601 keys and a stored `source`."""
    source = catalog.get("source")
    if not isinstance(source, str):
        raise MvaultError(f"vault '{name}' has an invalid catalog: 'source' must be a string")
    tracked = TRACKED_FIELDS if version == 3 else SOURCE_TRACKED_FIELDS
    groups = tuple(
        (CATEGORY_LABELS[category], _entry_list(name, catalog, category, tracked))
        for category in CATEGORIES
    )
    return CatalogView(
        version=version,
        source_url=source,
        groups=groups,
        tracked_fields=tracked,
        tracks_removal=version == 3,
        key_order=str,
    )


def _entry_list(name, catalog, field, tracked_fields):
    """The entry array at `field`, checked down to its tracked-field histories."""
    entries = catalog.get(field)
    if not isinstance(entries, list):
        raise MvaultError(f"vault '{name}' has an invalid catalog: '{field}' must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise MvaultError(f"vault '{name}' has an invalid catalog: {field} entry is not an object")
        for tracked in tracked_fields:
            history = entry.get(tracked)
            if not isinstance(history, dict) or not history:
                raise MvaultError(
                    f"vault '{name}' has an invalid catalog: {field} entry "
                    f"'{entry.get('id')}' field '{tracked}' is not a non-empty history object"
                )
    return entries
