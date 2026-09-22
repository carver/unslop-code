"""Finding the notable changes in a catalog of any supported version.

`digest` is the one command that never migrates: it reads a v1, v2 or v3 catalog
exactly as stored, using the version's rules from `formats` so the
classification below stays version-blind.
"""

from .changes import Change, group_changes
from .history import SOURCE_TRACKED_FIELDS


def collect_changes(data, form):
    """Notable changes as `{category: {group: [Change, ...]}}`."""
    return group_changes(
        (category, group, change)
        for category in form.categories
        for group, change in _classified(_entries(data, category), form)
    )


def _classified(entries, form):
    """The group and change record of each notable entry, in catalog order."""
    for entry in entries:
        classified = _classify(entry, form)
        if classified:
            yield classified


def _classify(entry, form):
    """The group and rendering of one entry, or None when nothing is notable."""
    histories = {field: _history(entry, field) for field in form.tracked_fields}
    change = Change(entry.get("id"), _current_title(histories["title"], form, entry.get("id")))

    if form.detects_removal and _is_removed(histories["removed"], form):
        return "removed", change
    if all(len(history) < 2 for history in histories.values()):
        return "added", change

    changed = tuple(
        field for field in SOURCE_TRACKED_FIELDS if _has_changed(histories[field], form)
    )
    reappeared = form.detects_removal and _has_changed(histories["removed"], form)
    if changed or reappeared:
        return "updated", Change(change.entry_id, change.title, changed, reappeared)
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
