"""The `digest` command: a read-only summary of a vault's notable changes.

Every entry lands in at most one group, chosen by the precedence removals,
additions, field updates; a group that catches no entry, and a category whose
groups are all empty, are left out of the report entirely.
"""

from .views import load_view

REMOVALS = "Removals"
ADDITIONS = "Additions"
UPDATES = "Field updates"
GROUP_ORDER = (REMOVALS, ADDITIONS, UPDATES)

REAPPEARED = "reappeared"
NO_CHANGES = "No notable changes found."


def digest_vault(name):
    """Print the digest of vault `name` to stdout."""
    view = load_view(name)
    report = [
        line for label, entries in view.groups for line in render_category(view, label, entries)
    ]
    print("\n".join(report) if report else NO_CHANGES)
    print(f"Digest of vault '{name}' (catalog version {view.version}) from {view.source}")


def render_category(view, label, entries):
    """The report lines for one category, or none when nothing is notable."""
    grouped = classify_entries(view, entries)
    lines = []
    for group in GROUP_ORDER:
        if grouped[group]:
            lines.append(f"  {group}:")
            lines.extend(f"    {entry_line(view, entry, group)}" for entry in grouped[group])
    return [f"{label}:", *lines] if lines else []


def classify_entries(view, entries):
    """One category's entries grouped by change type, keeping catalog order."""
    grouped = {group: [] for group in GROUP_ORDER}
    for entry in entries:
        group = classify(view, entry)
        if group:
            grouped[group].append(entry)
    return grouped


def classify(view, entry):
    """The group `entry` belongs to, or `None` when it changed nothing notable."""
    if view.detects_removals and is_removal(view, entry):
        return REMOVALS
    if all(len(view.history(entry, field)) < 2 for field in view.tracked):
        return ADDITIONS
    return UPDATES if changed_fields(view, entry) else None


def is_removal(view, entry):
    """Latest `removed` is true and the value before it, if any, is false."""
    values = view.history(entry, "removed")
    return bool(values) and values[-1] and (len(values) < 2 or not values[-2])


def changed_fields(view, entry):
    """The tracked fields whose latest two history values differ."""
    return [field for field in view.tracked if differs(view.history(entry, field))]


def differs(values):
    """Whether a history holds at least two values and its last two differ."""
    return len(values) > 1 and values[-1] != values[-2]


def entry_line(view, entry, group):
    """An entry's title, with the changed field names appended for updates."""
    title = view.current(entry, "title")
    if group != UPDATES:
        return title
    return f"{title} ({', '.join(update_notes(view, entry))})"


def update_notes(view, entry):
    """The changed field names, with a changed `removed` read as a reappearance."""
    fields = changed_fields(view, entry)
    reappearance = [REAPPEARED] if "removed" in fields else []
    return reappearance + [field for field in fields if field != "removed"]
