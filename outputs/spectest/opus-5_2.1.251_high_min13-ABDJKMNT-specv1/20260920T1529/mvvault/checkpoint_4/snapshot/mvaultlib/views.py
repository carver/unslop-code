"""Read-only views of a catalog in the layout of its own version.

`digest` must read v1, v2 and v3 vaults without migrating them, and the three
versions differ in how they group entries, which fields they track and how
their history keys order. A `CatalogView` answers those three questions so the
commands built on it never branch on a version number.
"""

from dataclasses import dataclass

from .catalog import read_catalog, validate_catalog
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS
from .source import CATEGORIES
from .versions import V1_SOURCE_TEMPLATE, VERSION, detect_version, require
from .viewer import default_category

CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}
V1_LABEL = "Entries"


@dataclass(frozen=True)
class CatalogView:
    """One catalog as its own version presents it."""

    version: int
    source: str
    #: `(label, category, entries)` per category, in the order reported.
    groups: tuple
    #: The tracked fields this version stores histories for.
    tracked: tuple
    #: Whether history keys are UNIX-epoch text, which orders numerically.
    epoch_keys: bool

    @property
    def detects_removals(self):
        """Whether entries carry the `removed` history removal detection needs."""
        return "removed" in self.tracked

    def entries(self, category):
        """The entries this version files under `category`."""
        return next(entries for _, name, entries in self.groups if name == category)

    def history(self, entry, field):
        """`entry[field]`'s values, oldest first in this version's key order."""
        stored = entry.get(field, {})
        return [stored[key] for key in sorted(stored, key=int if self.epoch_keys else str)]

    def current(self, entry, field):
        """The value of `entry[field]` at its latest history key."""
        return self.history(entry, field)[-1]


def load_view(name):
    """Read `<name>/catalog.json` in its own version's layout, without migrating."""
    catalog = read_catalog(name)
    version = detect_version(catalog, name)
    if version == 1:
        return v1_view(catalog, name)

    validate_catalog(catalog, name)
    groups = tuple(
        (CATEGORY_LABELS[category], category, catalog[category]) for category in CATEGORIES
    )
    tracked = TRACKED_FIELDS if version == VERSION else SOURCE_TRACKED_FIELDS
    return CatalogView(version, catalog["source"], groups, tracked, epoch_keys=False)


def v1_view(catalog, name):
    """Version 1: one flat `entries` list, and a source URL built from `source_id`."""
    source_id = require(catalog, "source_id", (str,), name)
    entries = require(catalog, "entries", (list,), name)
    return CatalogView(
        version=1,
        source=V1_SOURCE_TEMPLATE.format(source_id),
        groups=((V1_LABEL, default_category(1), entries),),
        tracked=SOURCE_TRACKED_FIELDS,
        epoch_keys=True,
    )
