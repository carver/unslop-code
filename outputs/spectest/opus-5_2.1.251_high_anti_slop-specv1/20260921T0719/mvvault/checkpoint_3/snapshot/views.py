"""Read-only views over a stored catalog of any supported version.

Commands that only report on a vault read it where it is instead of upgrading
it first.  A view hides what the versions disagree on -- how entries are
grouped, which fields they track, how their history keys order and where the
source lives -- behind one shape for every version.
"""

from dataclasses import dataclass
from typing import Any, Callable

import catalogs
import migrations
from catalogs import Entry

#: Label of the single group a version 1 catalog keeps all its entries in.
V1_GROUP = "Entries"

#: Sorts the history keys of a version, which are epoch seconds before v2.
KeyOrder = Callable[[str], Any]


@dataclass(frozen=True)
class CatalogView:
    """One stored catalog, seen through the conventions of its version."""

    version: int
    source: str
    groups: dict[str, list[Entry]]
    fields: tuple[str, ...]
    key_order: KeyOrder

    def observations(self, entry: Entry, field: str) -> list[Any]:
        """Every value a tracked field took, oldest first."""
        history = entry.get(field, {})
        return [history[key] for key in sorted(history, key=self.key_order)]


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
        groups={V1_GROUP: catalog.get("entries", [])},
        fields=catalogs.SOURCE_TRACKED_FIELDS,
        key_order=int,
    )


def _categorized_view(catalog: dict, version: int) -> CatalogView:
    """View of a version 2 or 3 catalog, which share layout and key format.

    Only version 3 carries the ``removed`` history, so only it can tell an
    entry that left the source from one that is merely unchanged.
    """
    return CatalogView(
        version=version,
        source=catalog.get("source", ""),
        groups={
            category.capitalize(): catalog.get(category, [])
            for category in catalogs.CATEGORIES
        },
        fields=catalogs.TRACKED_FIELDS if version == 3 else catalogs.SOURCE_TRACKED_FIELDS,
        key_order=str,
    )
