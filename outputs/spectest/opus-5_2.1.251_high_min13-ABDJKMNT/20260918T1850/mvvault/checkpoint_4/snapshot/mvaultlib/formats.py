"""How each supported catalog version stores what a reader needs.

`digest` and the viewer both read catalogs exactly as stored, whichever version
they declare. The differences between the three formats -- which categories
exist, whether removals can be detected, how history keys order, and where the
source URL comes from -- are collected here so their callers stay version-blind.
"""

from dataclasses import dataclass
from typing import Callable

from .catalog import CATEGORIES
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS, is_text
from .legacy import V1_SOURCE_TEMPLATE, read_version

#: The single category a version 1 catalog keeps all of its entries in.
V1_CATEGORIES = ("entries",)


@dataclass(frozen=True)
class CatalogFormat:
    """The reading rules of one catalog version.

    `key` is the comparison a history's timestamp keys sort by: v1 keys are
    UNIX-epoch numbers, later versions use ISO 8601 text that orders as text.
    """

    version: int
    categories: tuple
    tracked_fields: tuple
    detects_removal: bool
    key: Callable
    source: Callable

    @property
    def default_category(self):
        """The category a vault of this version opens on."""
        return self.categories[0]


def _v1_source(data):
    """A v1 catalog carries a platform id; its full URL is derived from it."""
    source_id = data.get("source_id")
    if not is_text(source_id):
        raise ValueError("version 1 catalog has no usable 'source_id'")
    return V1_SOURCE_TEMPLATE.format(source_id)


def _stored_source(data):
    source = data.get("source")
    if not is_text(source):
        raise ValueError("catalog has no usable source URL")
    return source


FORMATS = {
    1: CatalogFormat(
        version=1,
        categories=V1_CATEGORIES,
        tracked_fields=SOURCE_TRACKED_FIELDS,
        detects_removal=False,
        key=int,
        source=_v1_source,
    ),
    2: CatalogFormat(
        version=2,
        categories=CATEGORIES,
        tracked_fields=SOURCE_TRACKED_FIELDS,
        detects_removal=False,
        key=str,
        source=_stored_source,
    ),
    3: CatalogFormat(
        version=3,
        categories=CATEGORIES,
        tracked_fields=TRACKED_FIELDS,
        detects_removal=True,
        key=str,
        source=_stored_source,
    ),
}


def catalog_format(data):
    """The reading rules for the version `data` declares."""
    return FORMATS[read_version(data)]
