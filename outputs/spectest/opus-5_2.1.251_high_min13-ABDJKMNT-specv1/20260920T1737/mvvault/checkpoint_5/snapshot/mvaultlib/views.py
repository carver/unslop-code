"""Read-only, version-aware views over a stored catalog.

`digest` reports on v1, v2 and v3 vaults without migrating them, so instead of
upgrading a legacy catalog it reads it in its own shape. A `CatalogView` carries
everything that differs between versions: how entries are grouped, which tracked
fields exist, how history keys are ordered and where the source URL comes from.
"""

from dataclasses import dataclass

from mvaultlib.entries import SOURCE_TRACKED_FIELDS, STATIC_FIELD_TYPES, TRACKED_FIELDS
from mvaultlib.errors import MvaultError
from mvaultlib.timestamps import epoch_to_timestamp
from mvaultlib.versions import V1_SOURCE_URL, detect_version
from mvaultlib.viewer.links import V1_CATEGORY, valid_categories

#: Heading shown for each v2/v3 category, and for the single v1 group.
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}
V1_GROUP_LABEL = "Entries"


#: How a source-platform entry address extends the vault's source URL.
ENTRY_PATH = "entry"


@dataclass(frozen=True)
class Group:
    """One category of a catalog: its heading, its viewer route and its entries."""

    label: str
    category: str
    entries: list

    def find(self, entry_id):
        """The entry with `entry_id`, or None when this category has no such id.

        The search never leaves the group, so the same id held by another
        category is not a match.
        """
        found = [entry for entry in self.entries if entry["id"] == entry_id]
        return found[0] if found else None


@dataclass(frozen=True)
class CatalogView:
    """One stored catalog seen through the conventions of its own version."""

    version: int
    source_url: str
    #: The catalog's `Group`s in the order they should be reported.
    groups: tuple
    tracked_fields: tuple
    #: True when the version records a `removed` flag, so removals are detectable.
    tracks_removal: bool
    #: Key function putting history keys of this version in chronological order.
    key_order: type
    #: Renders a raw history key of this version as ISO 8601 chart-data text.
    chart_timestamp: type

    def ordered_keys(self, history):
        """The keys of one tracked-field history, oldest first."""
        return sorted(history, key=self.key_order)

    def current_value(self, history):
        """The value at the latest key of one tracked-field history."""
        return history[self.ordered_keys(history)[-1]]

    def entry_link(self, entry_id):
        """The source-platform address of one entry, derived for this version."""
        return f"{self.source_url.rstrip('/')}/{ENTRY_PATH}/{entry_id}"

    def group(self, category):
        """The group serving `category`, or None when the version has no such
        category. The comparison is case-sensitive, as the viewer requires."""
        found = [group for group in self.groups if group.category == category]
        return found[0] if found else None


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
        groups=(Group(V1_GROUP_LABEL, V1_CATEGORY, entries),),
        tracked_fields=SOURCE_TRACKED_FIELDS,
        tracks_removal=False,
        key_order=int,
        chart_timestamp=epoch_to_timestamp,
    )


def _modern_view(name, catalog, version):
    """v2 and v3: per-category groups, ISO 8601 keys and a stored `source`."""
    source = catalog.get("source")
    if not isinstance(source, str):
        raise MvaultError(f"vault '{name}' has an invalid catalog: 'source' must be a string")
    tracked = TRACKED_FIELDS if version == 3 else SOURCE_TRACKED_FIELDS
    groups = tuple(
        Group(CATEGORY_LABELS[category], category, _entry_list(name, catalog, category, tracked))
        for category in valid_categories(version)
    )
    return CatalogView(
        version=version,
        source_url=source,
        groups=groups,
        tracked_fields=tracked,
        tracks_removal=version == 3,
        key_order=str,
        chart_timestamp=str,
    )


def _entry_list(name, catalog, field, tracked_fields):
    """The entry array at `field`, checked down to its tracked-field histories."""
    entries = catalog.get(field)
    if not isinstance(entries, list):
        raise MvaultError(f"vault '{name}' has an invalid catalog: '{field}' must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise MvaultError(f"vault '{name}' has an invalid catalog: {field} entry is not an object")
        for static, expected in STATIC_FIELD_TYPES.items():
            if not isinstance(entry.get(static), expected) or isinstance(entry.get(static), bool):
                raise MvaultError(
                    f"vault '{name}' has an invalid catalog: {field} entry "
                    f"has a missing or mistyped '{static}'"
                )
        for tracked in tracked_fields:
            history = entry.get(tracked)
            if not isinstance(history, dict) or not history:
                raise MvaultError(
                    f"vault '{name}' has an invalid catalog: {field} entry "
                    f"'{entry.get('id')}' field '{tracked}' is not a non-empty history object"
                )
    return entries
