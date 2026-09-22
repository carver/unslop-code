"""Human-readable summary of the notable changes recorded in a vault.

The digest reads a catalog in the shape of its own version, so it works on a
legacy vault without migrating it, and never writes anything back. Each entry is
assigned to at most one group: a removal wins over an addition, and an addition
wins over a field update.
"""

from typing import NamedTuple

from . import catalog, versions

REMOVED = "removed"
#: Groups in the order their headings are printed, keyed by the classifier's name.
GROUP_HEADINGS = {"added": "Added", REMOVED: "Removed", "updated": "Updated"}
#: Name a changed ``removed`` field is reported under once the entry is back.
REAPPEARED_LABEL = "reappeared"
NO_CHANGES = "No notable changes found."


class Change(NamedTuple):
    """One entry's place in the digest: its group, current title and changed fields."""

    group: str
    title: str
    fields: tuple


def report(name, moment):
    """Render the digest of the vault called ``name`` as text, stamped with ``moment``."""
    loaded = versions.view(catalog.read_document(name), name)
    sections = [_section(label, entries, loaded) for label, _, entries in loaded.categories]
    lines = [section for section in sections if section] or [NO_CHANGES]
    return "\n".join(lines + ["", _trailer(name, loaded, moment)])


def _section(label, entries, loaded):
    """Render one category block grouped by change type, or ``None`` when nothing changed."""
    changes = [change for change in (_change(entry, loaded) for entry in entries) if change]
    if not changes:
        return None
    lines = [f"{label}:"]
    for group, heading in GROUP_HEADINGS.items():
        listed = [change for change in changes if change.group == group]
        if not listed:
            continue
        lines.append(f"  {heading}:")
        lines.extend(f"    - {_entry_text(change)}" for change in listed)
    return "\n".join(lines)


def _change(entry, loaded):
    """Classify one entry, or return ``None`` when it shows no notable change."""
    title = _current(entry["title"], loaded.key_order)
    if REMOVED in loaded.fields and _is_removal(entry[REMOVED], loaded.key_order):
        return Change(REMOVED, title, ())
    if all(len(entry[field]) < 2 for field in loaded.fields):
        return Change("added", title, ())
    changed = tuple(
        _field_label(field)
        for field in loaded.fields
        if _is_update(entry[field], loaded.key_order)
    )
    return Change("updated", title, changed) if changed else None


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
    return REAPPEARED_LABEL if field == REMOVED else field


def _current(history, key_order):
    """Return the value recorded at the latest key, compared in this version's order."""
    return history[max(history, key=key_order)]


def _entry_text(change):
    """Render an entry line: its current title, followed by the fields that changed."""
    if not change.fields:
        return change.title
    return f"{change.title} ({', '.join(change.fields)})"


def _trailer(name, loaded, moment):
    """Render the closing line describing the vault, version and source the digest read."""
    return (
        f"Digest of vault '{name}' (catalog version {loaded.version}) "
        f"from {loaded.source} at {moment}"
    )
