"""Human-readable reports printed to stdout: the digest and the sync summary.

Every line that names a changed entry carries the viewer link that opens it,
so a report read in a terminal leads straight to the entry in a browser.
"""

from . import digest, links
from .timestamps import format_timestamp

INDENT = "  "
NO_CHANGES = "No notable changes found."
REAPPEARED = "reappeared"
LINK_GAP = "  "


def render_digest(view, name, generated_at):
    """Render the notable changes of the vault ``name`` as a digest report."""
    lines = []
    for category in digest.summarize(view):
        lines.append(category.label)
        for group, changes in category.groups:
            lines.append(INDENT + group)
            lines.extend(
                INDENT * 2 + _digest_line(name, category.category, change) for change in changes
            )
    if not lines:
        lines.append(NO_CHANGES)
    lines.append(_trailer(view, generated_at))
    return "\n".join(lines)


def _digest_line(name, category, change):
    """One entry line: its title, what about it changed, and its viewer link."""
    notes = ([REAPPEARED] if change.reappeared else []) + list(change.fields)
    titled = f"{change.title} ({', '.join(notes)})" if notes else change.title
    return titled + LINK_GAP + links.entry_url(name, category, change.identifier)


def _trailer(view, generated_at):
    """The closing line naming the vault's source, version and digest time."""
    return (
        f"-- digest of {view.source} (catalog version {view.version})"
        f" at {format_timestamp(generated_at)}"
    )


def sync_summary(name, changes):
    """Render a sync's counts, followed by a line per entry it changed."""
    counts = (
        f"Sync summary: {changes.added} added, {changes.removed} removed,"
        f" {changes.updated} updated"
    )
    return "\n".join([counts] + [INDENT + _sync_line(name, change) for change in changes.entries])


def _sync_line(name, change):
    """One changed entry: what became of it, its title and its viewer link."""
    link = links.entry_url(name, change.category, change.identifier)
    return f"{change.kind}: {change.title}" + LINK_GAP + link
