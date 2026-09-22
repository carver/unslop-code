"""Read-only views over a stored catalog of any supported version.

Commands that only report on a vault read it where it is instead of upgrading
it first.  A view hides what the versions disagree on -- how entries are
grouped, which fields they track, how their history keys order and where the
source lives -- behind one shape for every version.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import catalogs
import migrations
from catalogs import Entry
from timestamps import from_epoch

#: Route and report name of the single group a version 1 catalog keeps.
V1_CATEGORY = "entries"

#: Sorts the history keys of a version, which are epoch seconds before v2.
KeyOrder = Callable[[str], Any]

#: Renders a stored history key of a version as canonical timestamp text.
KeyTimestamp = Callable[[str], str]


@dataclass(frozen=True)
class CatalogGroup:
    """One group of entries: its route name, its heading and its entries."""

    category: str
    entries: list[Entry]

    @property
    def label(self) -> str:
        """Heading a report prints the group under."""
        return self.category.capitalize()

    def entry(self, identifier: str) -> Optional[Entry]:
        """The entry this group holds under ``identifier``, if it holds one.

        Nothing outside the group is considered, so the same identifier in
        another category is not an answer here.
        """
        return next((entry for entry in self.entries if entry["id"] == identifier), None)


@dataclass(frozen=True)
class CatalogView:
    """One stored catalog, seen through the conventions of its version."""

    version: int
    source: str
    groups: tuple[CatalogGroup, ...]
    fields: tuple[str, ...]
    key_order: KeyOrder
    key_timestamp: KeyTimestamp

    @property
    def default_category(self) -> str:
        """The category a vault of this version is opened on."""
        return self.groups[0].category

    @property
    def categories(self) -> tuple[str, ...]:
        """Every category this version addresses entries by."""
        return tuple(group.category for group in self.groups)

    def group(self, category: str) -> Optional[CatalogGroup]:
        """The group a category names, or ``None`` when it names none."""
        return next((group for group in self.groups if group.category == category), None)

    def series(self, entry: Entry, field: str) -> list[tuple[str, Any]]:
        """Every observation of a tracked field as a timestamp and a value.

        Observations come oldest first, ordered the way the stored version
        orders its history keys, and their timestamps are canonical text
        whatever format those keys are written in.
        """
        history = entry.get(field, {})
        return [
            (self.key_timestamp(key), history[key])
            for key in sorted(history, key=self.key_order)
        ]

    def observations(self, entry: Entry, field: str) -> list[Any]:
        """Every value a tracked field took, oldest first."""
        return [value for _, value in self.series(entry, field)]

    def current(self, entry: Entry, field: str) -> Any:
        """The value a tracked field holds now, or ``None`` when untracked.

        Versions before 3 track no removal flag, so asking one of them
        whether an entry is removed answers ``None``.
        """
        observations = self.observations(entry, field)
        return observations[-1] if observations else None

    def entry_source(self, identifier: str) -> str:
        """The page an entry has on the platform the vault tracks.

        A version 1 vault names its platform rather than its feed, but its
        view already stands for the URL that platform lives at, so one shape
        serves every version.
        """
        return f"{self.source.rstrip('/')}/entry/{identifier}"


def open_view(catalog: Any, name: str) -> CatalogView:
    """Return the view of the catalog of vault ``name`` as stored on disk."""
    version = migrations.version_of(catalog, name)
    if version == 1:
        return _v1_view(catalog)
    return _categorized_view(catalog, version)


def _v1_view(catalog: dict) -> CatalogView:
    """View of a flat version 1 catalog under its derived platform URL."""
    return CatalogView(
        version=1,
        source=migrations.V1_SOURCE.format(source_id=catalog.get("source_id")),
        groups=(CatalogGroup(V1_CATEGORY, catalog.get("entries", [])),),
        fields=catalogs.SOURCE_TRACKED_FIELDS,
        key_order=int,
        key_timestamp=from_epoch,
    )


def _categorized_view(catalog: dict, version: int) -> CatalogView:
    """View of a version 2 or 3 catalog, which share layout and key format.

    Only version 3 carries the ``removed`` history, so only it can tell an
    entry that left the source from one that is merely unchanged.
    """
    return CatalogView(
        version=version,
        source=catalog.get("source", ""),
        groups=tuple(
            CatalogGroup(category, catalog.get(category, []))
            for category in catalogs.CATEGORIES
        ),
        fields=catalogs.TRACKED_FIELDS if version == 3 else catalogs.SOURCE_TRACKED_FIELDS,
        key_order=str,
        key_timestamp=str,
    )
