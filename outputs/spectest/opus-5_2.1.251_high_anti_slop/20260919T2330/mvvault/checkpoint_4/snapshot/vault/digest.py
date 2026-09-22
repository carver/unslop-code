"""Human-readable summaries of the changes a vault records.

The digest reads a catalog in the shape of its own version, so it works on a
legacy vault without migrating it, and never writes anything back. Each entry is
assigned to at most one group: a removal wins over an addition, and an addition
wins over a field update. The post-sync summary renders the same groups from the
records a sync just produced. Every reported entry carries the viewer link that
opens it in the local browser viewer.
"""

from collections import Counter
from typing import NamedTuple

from . import catalog, versions, viewer
from .changes import ADDED, HEADINGS, REAPPEARED, REMOVED, UPDATED
from .history import current_value

NO_CHANGES = "No notable changes found."


class Change(NamedTuple):
    """One reported entry: its group, current title, changed fields and viewer link."""

    group: str
    title: str
    fields: tuple
    link: str


def report(name, moment):
    """Render the digest of the vault called ``name`` as text, stamped with ``moment``."""
    loaded = versions.view(catalog.read_document(name), name)
    sections = [
        _section(label, _classified(name, loaded, category, entries))
        for label, category, entries in loaded.categories
    ]
    lines = [section for section in sections if section] or [NO_CHANGES]
    return "\n".join(lines + ["", _trailer(name, loaded, moment)])


def sync_report(name, recorded):
    """Render what a sync changed: the counts line, then the entries of each category."""
    tallies = Counter(change.group for change in recorded)
    lines = [", ".join(f"{tallies[group]} {group}" for group in HEADINGS)]
    for category in catalog.CATEGORIES:
        listed = [_synced(name, change) for change in recorded if change.category == category]
        section = _section(category.capitalize(), listed)
        if section:
            lines.append(section)
    return "\n".join(lines)


def _classified(name, loaded, category, entries):
    """Classify the entries of one category, dropping those with nothing to report."""
    route = viewer.route_category(loaded.version, category)
    reported = (_change(name, route, entry, loaded) for entry in entries)
    return [change for change in reported if change]


def _change(name, route, entry, loaded):
    """Classify one stored entry, or return ``None`` when it shows no notable change."""
    title = versions.latest_value(entry["title"], loaded.key_order)
    link = viewer.entry_link(name, route, entry["id"])
    removed = catalog.REMOVED_FIELD
    if removed in loaded.fields and _is_removal(entry[removed], loaded.key_order):
        return Change(REMOVED, title, (), link)
    if all(len(entry[field]) < 2 for field in loaded.fields):
        return Change(ADDED, title, (), link)
    changed = tuple(
        _field_label(field)
        for field in loaded.fields
        if _is_update(entry[field], loaded.key_order)
    )
    return Change(UPDATED, title, changed, link) if changed else None


def _synced(name, change):
    """Turn one entry a sync changed into a reported change, with its viewer link."""
    entry = change.entry
    return Change(
        change.group,
        current_value(entry["title"]),
        change.fields,
        viewer.entry_link(name, change.category, entry["id"]),
    )


def _section(label, changes):
    """Render one category block grouped by change kind, or ``None`` when nothing changed."""
    if not changes:
        return None
    lines = [f"{label}:"]
    for group, heading in HEADINGS.items():
        listed = [change for change in changes if change.group == group]
        if not listed:
            continue
        lines.append(f"  {heading}:")
        lines.extend(f"    - {_entry_text(change)}" for change in listed)
    return "\n".join(lines)


def _is_removal(history, key_order):
    """Tell whether the latest ``removed`` observation took the entry out of the source."""
    keys = sorted(history, key=key_order)
    return history[keys[-1]] is True and (len(keys) < 2 or history[keys[-2]] is False)


def _is_update(history, key_order):
    """Tell whether a field was observed at least twice with differing latest values."""
    keys = sorted(history, key=key_order)
    return len(keys) >= 2 and history[keys[-1]] != history[keys[-2]]


def _field_label(field):
    """Name a changed field; a flipped ``removed`` flag in this group means a reappearance."""
    return REAPPEARED if field == catalog.REMOVED_FIELD else field


def _entry_text(change):
    """Render an entry line: its title, the fields that changed and its viewer link."""
    fields = f" ({', '.join(change.fields)})" if change.fields else ""
    return f"{change.title}{fields} {change.link}"


def _trailer(name, loaded, moment):
    """Render the closing line describing the vault, version and source the digest read."""
    return (
        f"Digest of vault '{name}' (catalog version {loaded.version}) "
        f"from {loaded.source} at {moment}"
    )
