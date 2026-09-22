"""Reading a catalog of any supported version to find its notable changes.

`digest` is the one command that never migrates: it reads a v1, v2 or v3 catalog
exactly as stored. The differences between the three formats -- how categories
are named, whether removals can be detected, and how history keys order -- are
collected in a `CatalogFormat` so the classification below stays version-blind.
"""

from dataclasses import dataclass
from typing import Callable

from .catalog import CATEGORIES
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS, is_text
from .legacy import V1_SOURCE_TEMPLATE, read_version

#: Change groups in the order they take precedence, and so the order they print.
GROUP_ORDER = ("removed", "added", "updated")

#: The category sections of a v2 or v3 digest, label paired with catalog field.
CATEGORY_GROUPS = tuple((category.capitalize(), category) for category in CATEGORIES)


@dataclass(frozen=True)
class Change:
    """One entry that qualifies for a digest group.

    `fields` names the tracked fields whose value changed, and `reappeared` says
    the entry came back after having been removed. Both are empty for an entry
    that is merely an addition or a removal.
    """

    title: str
    fields: tuple = ()
    reappeared: bool = False


@dataclass(frozen=True)
class CatalogFormat:
    """How one catalog version stores everything `digest` needs to read."""

    version: int
    groups: tuple
    tracked_fields: tuple
    detects_removal: bool
    key: Callable
    source: Callable


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
        groups=(("Entries", "entries"),),
        tracked_fields=SOURCE_TRACKED_FIELDS,
        detects_removal=False,
        key=int,
        source=_v1_source,
    ),
    2: CatalogFormat(
        version=2,
        groups=CATEGORY_GROUPS,
        tracked_fields=SOURCE_TRACKED_FIELDS,
        detects_removal=False,
        key=str,
        source=_stored_source,
    ),
    3: CatalogFormat(
        version=3,
        groups=CATEGORY_GROUPS,
        tracked_fields=TRACKED_FIELDS,
        detects_removal=True,
        key=str,
        source=_stored_source,
    ),
}


def catalog_format(data):
    """The reading rules for the version `data` declares."""
    return FORMATS[read_version(data)]


def collect_changes(data, form):
    """Notable changes as `{category label: {group: [Change, ...]}}`.

    Categories with nothing to report are left out entirely, and within a
    category the groups appear in precedence order.
    """
    grouped = {}
    for label, field in form.groups:
        changes = _category_changes(_entries(data, field), form)
        if changes:
            grouped[label] = changes
    return grouped


def _category_changes(entries, form):
    """Classify one category's entries, keeping catalog order inside each group."""
    groups = {}
    for entry in entries:
        classified = _classify(entry, form)
        if classified:
            group, change = classified
            groups.setdefault(group, []).append(change)
    return {group: groups[group] for group in GROUP_ORDER if group in groups}


def _classify(entry, form):
    """The group and rendering of one entry, or None when nothing is notable."""
    histories = {field: _history(entry, field) for field in form.tracked_fields}
    title = _current_title(histories["title"], form, entry.get("id"))

    if form.detects_removal and _is_removed(histories["removed"], form):
        return "removed", Change(title)
    if all(len(history) < 2 for history in histories.values()):
        return "added", Change(title)

    changed = tuple(
        field for field in SOURCE_TRACKED_FIELDS if _has_changed(histories[field], form)
    )
    reappeared = form.detects_removal and _has_changed(histories["removed"], form)
    if changed or reappeared:
        return "updated", Change(title, changed, reappeared)
    return None


def _is_removed(history, form):
    """The removal rule: latest value true, and the one before it -- if any -- false."""
    values = _ordered_values(history, form)
    if not values or values[-1] is not True:
        return False
    return len(values) < 2 or values[-2] is False


def _has_changed(history, form):
    """Two or more observations whose latest two values differ."""
    values = _ordered_values(history, form)
    return len(values) >= 2 and values[-1] != values[-2]


def _ordered_values(history, form):
    """A history's values, ordered by the version's key comparison."""
    return [history[key] for key in sorted(history, key=form.key)]


def _current_title(history, form, entry_id):
    """The latest recorded title, which every usable entry must have."""
    values = _ordered_values(history, form)
    if not values:
        raise ValueError(f"entry {entry_id!r} has no recorded title")
    return values[-1]


def _entries(data, field):
    """One category's stored entries, checked far enough to be readable."""
    entries = data.get(field)
    if not isinstance(entries, list):
        raise ValueError(f"catalog field {field!r} is missing or not an array")
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {field}[{position}] is not an object")
    return entries


def _history(entry, field):
    """One tracked field's history object."""
    history = entry.get(field)
    if not isinstance(history, dict):
        raise ValueError(f"entry {entry.get('id')!r} has no {field!r} history object")
    return history
