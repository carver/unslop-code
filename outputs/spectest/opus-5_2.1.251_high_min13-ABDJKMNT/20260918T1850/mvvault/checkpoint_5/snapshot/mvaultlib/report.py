"""Rendering the two human-readable outputs: the digest and the sync summary.

Both report the same thing -- entries that changed, grouped by category and by
kind of change -- so both are rendered from the same grouped changes, and every
entry line ends in the viewer link that opens it.
"""

from collections import Counter

from .links import entry_link

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
    total = sum(count_changes(grouped).values())
    trailer = (
        f"Digest for vault {name!r} (catalog version {version}) at {generated}; "
        f"{total} notable changes; source: {source_url}"
    )
    return "\n\n".join(_render_sections(name, grouped) or [NO_CHANGES]) + f"\n\n{trailer}"


def render_sync_summary(name, grouped):
    """The post-sync report: what changed, then how much changed."""
    counts = count_changes(grouped)
    tally = (
        f"Sync summary: {counts['added']} added, "
        f"{counts['removed']} removed, {counts['updated']} updated"
    )
    return "\n\n".join([*_render_sections(name, grouped), tally])


def count_changes(grouped):
    """How many entries each change group holds, across every category."""
    counts = Counter()
    for groups in grouped.values():
        for group, changes in groups.items():
            counts[group] += len(changes)
    return counts


def _render_sections(name, grouped):
    """One section per category that has something to report."""
    return [_render_category(name, category, groups) for category, groups in grouped.items()]


def _render_category(name, category, groups):
    """One category section: its heading, then each group and its entries."""
    lines = [f"{category.capitalize()}:"]
    for group, changes in groups.items():
        lines.append(f"{INDENT}{GROUP_HEADINGS[group]}:")
        lines.extend(
            f"{INDENT * 2}{_render_change(name, category, change)}" for change in changes
        )
    return "\n".join(lines)


def _render_change(name, category, change):
    """An entry line: its current title, what changed, and its viewer link."""
    marks = (REAPPEARED, *change.fields) if change.reappeared else change.fields
    suffix = f" ({', '.join(marks)})" if marks else ""
    return f"{change.title}{suffix} {entry_link(name, category, change.entry_id)}"
