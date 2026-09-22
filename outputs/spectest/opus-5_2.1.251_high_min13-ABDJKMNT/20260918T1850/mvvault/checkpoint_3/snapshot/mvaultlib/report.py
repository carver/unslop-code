"""Rendering the two human-readable outputs: the digest and the sync summary."""

INDENT = "  "

#: Heading each change group prints under, keyed by the group name.
GROUP_HEADINGS = {"removed": "Removed", "added": "Added", "updated": "Updated"}

NO_CHANGES = "No notable changes found."

#: Word marking an entry that came back after having been removed.
REAPPEARED = "reappeared"


def render_digest(name, version, source_url, grouped, generated):
    """The digest document: one section per changed category, then a trailing line.

    `grouped` is the mapping `collect_changes` produces. `generated` is the text
    of the moment the digest was taken, the one wall-clock value a digest shows.
    """
    sections = [_render_category(label, groups) for label, groups in grouped.items()]
    total = sum(len(changes) for groups in grouped.values() for changes in groups.values())
    trailer = (
        f"Digest for vault {name!r} (catalog version {version}) at {generated}; "
        f"{total} notable changes; source: {source_url}"
    )
    return "\n\n".join(sections or [NO_CHANGES]) + f"\n\n{trailer}"


def _render_category(label, groups):
    """One category section: its heading, then each group and its entries."""
    lines = [f"{label}:"]
    for group, changes in groups.items():
        lines.append(f"{INDENT}{GROUP_HEADINGS[group]}:")
        lines.extend(f"{INDENT * 2}{_render_change(change)}" for change in changes)
    return "\n".join(lines)


def _render_change(change):
    """An entry line: its current title, and what changed about it in parentheses."""
    marks = change.fields
    if change.reappeared:
        marks = (REAPPEARED, *marks)
    return f"{change.title} ({', '.join(marks)})" if marks else change.title


def render_sync_summary(changes):
    """The post-sync line: how many entries were added, removed and updated."""
    return (
        f"Sync summary: {changes['added']} added, "
        f"{changes['removed']} removed, {changes['updated']} updated"
    )
