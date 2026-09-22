"""Reading a catalog of any stored version and grouping its notable changes.

A digest never upgrades and never writes: it reads the catalog as it lies on
disk and adapts to the version it finds. That costs a view of what the version
offers — which categories exist, which tracked fields it carries, how its
history keys order — and buys a digest of a legacy vault without migrating it.
"""

from collections import namedtuple

from . import catalog, history, versions
from .entries import REMOVED_FIELD, TRACKED_FIELDS
from .errors import VaultError
from .source import CATEGORIES

V1_GROUP = "Entries"
V1_CATEGORY = "entries"
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}

REMOVALS = "Removed"
ADDITIONS = "Added"
UPDATES = "Updated"
#: Group order, which is also the precedence used to place an entry in one.
GROUP_ORDER = (REMOVALS, ADDITIONS, UPDATES)

#: One category of a catalog: the label a report prints, the category name the
#: version stores it under, and the entries it holds in catalog order.
Group = namedtuple("Group", "label category entries")

#: A catalog seen through the shape of its own version. ``groups`` holds its
#: categories, ``tracked`` names the histories the version carries, and
#: ``ordering`` is the key function their history keys sort by.
CatalogView = namedtuple("CatalogView", "version source groups tracked ordering")

#: One entry's change: its id and current title, the tracked fields that
#: changed, and whether it is back after a removal.
Change = namedtuple("Change", "group identifier title fields reappeared")

#: One category's changes, split into non-empty groups of ``(label, changes)``.
CategoryDigest = namedtuple("CategoryDigest", "label category groups")


def load(name):
    """Return the vault ``name`` as a :class:`CatalogView` of its own version."""
    stored = catalog.read(name)
    version = versions.detect(name, stored)
    if version == 1:
        entries = _read_entries(name, stored, V1_CATEGORY, TRACKED_FIELDS)
        groups = [Group(V1_GROUP, V1_CATEGORY, entries)]
        return CatalogView(version, _v1_source(name, stored), groups, TRACKED_FIELDS, int)
    tracked = TRACKED_FIELDS + (REMOVED_FIELD,) if version == versions.VERSION else TRACKED_FIELDS
    groups = [
        Group(
            CATEGORY_LABELS[category],
            category,
            _read_entries(name, stored, category, tracked),
        )
        for category in CATEGORIES
    ]
    return CatalogView(version, _source_url(name, stored), groups, tracked, str)


def summarize(view):
    """Return the :class:`CategoryDigest` of every category that changed.

    Categories and groups keep their fixed order, entries their catalog order,
    so the same vault always digests to the same report.
    """
    return [found for found in (_digest_category(view, group) for group in view.groups) if found]


def _digest_category(view, group):
    """Group one category's changes by kind, or return ``None`` if it has none."""
    changes = [change for change in (_classify(view, entry) for entry in group.entries) if change]
    kinds = [(name, [change for change in changes if change.group == name]) for name in GROUP_ORDER]
    filled = [(name, found) for name, found in kinds if found]
    return CategoryDigest(group.label, group.category, filled) if filled else None


def _classify(view, entry):
    """Place ``entry`` in the first group it qualifies for, or in none at all."""
    identifier = entry["id"]
    title = history.latest_value(entry["title"], view.ordering) or identifier
    if REMOVED_FIELD in view.tracked and _is_removed(entry[REMOVED_FIELD], view.ordering):
        return Change(REMOVALS, identifier, title, (), False)
    if all(len(entry[field]) < 2 for field in view.tracked):
        return Change(ADDITIONS, identifier, title, (), False)
    changed = [field for field in view.tracked if _has_update(entry[field], view.ordering)]
    if not changed:
        return None
    fields = tuple(field for field in changed if field != REMOVED_FIELD)
    return Change(UPDATES, identifier, title, fields, REMOVED_FIELD in changed)


def _is_removed(history, ordering):
    """Whether the newest removal point says the entry is gone for good."""
    keys = sorted(history, key=ordering)
    if not keys or history[keys[-1]] is not True:
        return False
    return len(keys) < 2 or history[keys[-2]] is False


def _has_update(history, ordering):
    """Whether the two newest points of a history hold different values."""
    keys = sorted(history, key=ordering)
    return len(keys) >= 2 and history[keys[-1]] != history[keys[-2]]


def _v1_source(name, stored):
    """Derive a version 1 vault's source URL from its short source id."""
    if not isinstance(stored.get("source_id"), str):
        raise VaultError(f"vault {name} has no source id")
    return versions.V1_SOURCE_TEMPLATE.format(stored["source_id"])


def _source_url(name, stored):
    """Read the source URL a version 2 or 3 catalog stores outright."""
    if not isinstance(stored.get("source"), str):
        raise VaultError(f"vault {name} has no source URL")
    return stored["source"]


def _read_entries(name, stored, key, tracked):
    """Return the entries at ``key``, checked for the fields a digest reads."""
    listing = stored.get(key)
    if not isinstance(listing, list):
        raise VaultError(f"vault {name} is missing the {key} array")
    for entry in listing:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise VaultError(f"vault {name} holds an entry without an id")
        missing = [field for field in tracked if not isinstance(entry.get(field), dict)]
        if missing:
            raise VaultError(
                f"vault {name} entry {entry['id']} has no {', '.join(missing)} history"
            )
    return listing
